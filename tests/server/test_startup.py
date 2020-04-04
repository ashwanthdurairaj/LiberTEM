import json

import pytest
import websockets

from utils import assert_msg
from aio_utils import (
    create_connection, create_analysis, create_update_compound_analysis,
)

pytestmark = [pytest.mark.functional]


def _get_raw_params(path):
    return {
        "dataset": {
            "params": {
                "type": "RAW",
                "path": path,
                "dtype": "float32",
                "detector_size": [128, 128],
                "enable_direct": False,
                "scan_size": [16, 16]
            }
        }
    }


@pytest.mark.asyncio
async def test_start_server(base_url, http_client):
    """
    start the server and HTTP GET '/', which should
    return a 200 status code
    """
    url = base_url
    async with http_client.get(url) as response:
        assert response.status == 200
        print(await response.text())


@pytest.mark.asyncio
async def test_get_config(base_url, http_client):
    url = "{}/api/config/".format(base_url)
    async with http_client.get(url) as response:
        assert response.status == 200
        config = await response.json()
        assert set(config.keys()) == set(["status", "messageType", "config"])
        assert set(config['config'].keys()) == set([
            "version", "revision", "localCores", "cwd", "separator", "resultFileFormats",
        ])


@pytest.mark.asyncio
async def test_conn_is_disconnected(base_url, http_client):
    url = "{}/api/config/connection/".format(base_url)
    async with http_client.get(url) as response:
        assert response.status == 200
        conn = await response.json()
        print(conn)
        assert conn['status'] == 'disconnected'
        assert conn['connection'] == {}


@pytest.mark.asyncio
async def test_conn_connect_local(base_url, http_client):
    url = "{}/api/config/connection/".format(base_url)
    conn_details = {
        'connection': {
            'type': 'local',
            'numWorkers': 2,
        }
    }
    async with http_client.put(url, json=conn_details) as response:
        assert response.status == 200
        conn_resp = await response.json()
        assert conn_resp == {
            "status": "ok",
            "connection": {
                "type": "local",
                "numWorkers": 2,
            }
        }

    async with http_client.get(url) as response:
        assert response.status == 200
        conn = await response.json()
        assert conn == {
            "status": "ok",
            "connection": {
                "type": "local",
                "numWorkers": 2,
            }
        }


@pytest.mark.asyncio
async def test_cluster_connect_error(base_url, http_client):
    url = "{}/api/config/connection/".format(base_url)
    conn_details = {
        'connection': {
            'type': 'TCP',
            'address': 'tcp://unknown:8786',
        }
    }
    async with http_client.put(url, json=conn_details) as response:
        assert response.status == 200
        conn_resp = await response.json()
        assert_msg(conn_resp, 'CLUSTER_CONN_ERROR', status='error')


@pytest.mark.asyncio
async def test_initial_state_empty(default_raw, base_url, http_client, server_port):
    conn_url = "{}/api/config/connection/".format(base_url)
    conn_details = {
        'connection': {
            'type': 'local',
            'numWorkers': 2,
        }
    }
    async with http_client.put(conn_url, json=conn_details) as response:
        assert response.status == 200

    # connect to ws endpoint:
    ws_url = "ws://127.0.0.1:{}/api/events/".format(server_port)
    async with websockets.connect(ws_url) as ws:
        initial_msg = json.loads(await ws.recv())
        assert initial_msg['messageType'] == "INITIAL_STATE"
        assert initial_msg['status'] == "ok"
        assert initial_msg['datasets'] == []
        assert initial_msg['jobs'] == []
        assert initial_msg['analyses'] == []


@pytest.mark.asyncio
async def test_initial_state_w_existing_ds(default_raw, base_url, http_client, server_port):
    conn_url = "{}/api/config/connection/".format(base_url)
    conn_details = {
        'connection': {
            'type': 'local',
            'numWorkers': 2,
        }
    }
    async with http_client.put(conn_url, json=conn_details) as response:
        assert response.status == 200

    # first connect has empty list of datasets:
    ws_url = "ws://127.0.0.1:{}/api/events/".format(server_port)
    async with websockets.connect(ws_url) as ws:
        initial_msg = json.loads(await ws.recv())
        assert initial_msg['messageType'] == "INITIAL_STATE"
        assert initial_msg['status'] == "ok"
        assert initial_msg['datasets'] == []

    raw_path = default_raw._path

    ds_uuid = "ae5d23bd-1f2a-4c57-bab2-dfc59a1219f3"
    ds_url = "{}/api/datasets/{}/".format(
        base_url, ds_uuid
    )
    ds_params = _get_raw_params(raw_path)
    async with http_client.put(ds_url, json=ds_params) as resp:
        assert resp.status == 200
        resp_json = await resp.json()
        assert_msg(resp_json, 'CREATE_DATASET')
        for k in ds_params['dataset']['params']:
            assert ds_params['dataset']['params'][k] == resp_json['details']['params'][k]

    # second connect has one dataset:
    async with websockets.connect(ws_url) as ws:
        initial_msg = json.loads(await ws.recv())
        assert initial_msg['messageType'] == "INITIAL_STATE"
        assert initial_msg['status'] == "ok"
        assert len(initial_msg['datasets']) == 1
        assert initial_msg['datasets'][0]["id"] == ds_uuid
        assert initial_msg['datasets'][0]["params"] == {
            "type": "RAW",
            "path": raw_path,
            "dtype": "float32",
            "detector_size": [128, 128],
            "enable_direct": False,
            "scan_size": [16, 16],
            "shape": [16, 16, 128, 128],
        }


@pytest.mark.asyncio
async def test_initial_state_analyses(default_raw, base_url, http_client, server_port):
    await create_connection(base_url, http_client)

    # first connect has empty list of datasets:
    ws_url = "ws://127.0.0.1:{}/api/events/".format(server_port)
    async with websockets.connect(ws_url) as ws:
        initial_msg = json.loads(await ws.recv())
        assert initial_msg['messageType'] == "INITIAL_STATE"
        assert initial_msg['status'] == "ok"
        assert initial_msg['datasets'] == []

    raw_path = default_raw._path

    ds_uuid = "ae5d23bd-1f2a-4c57-bab2-dfc59a1219f3"
    ds_url = "{}/api/datasets/{}/".format(
        base_url, ds_uuid
    )
    ds_params = _get_raw_params(raw_path)
    async with http_client.put(ds_url, json=ds_params) as resp:
        assert resp.status == 200
        resp_json = await resp.json()
        assert_msg(resp_json, 'CREATE_DATASET')
        for k in ds_params['dataset']['params']:
            assert ds_params['dataset']['params'][k] == resp_json['details']['params'][k]

        async with websockets.connect(ws_url) as ws:
            initial_msg = json.loads(await ws.recv())
            assert initial_msg['messageType'] == "INITIAL_STATE"

            ca_uuid, ca_url = await create_update_compound_analysis(
                ws, http_client, base_url, ds_uuid,
            )

            analysis_uuid, analysis_url = await create_analysis(
                ws, http_client, base_url, ds_uuid, ca_uuid, details={
                    "analysisType": "SUM_FRAMES",
                    "parameters": {
                        "roi": {
                            "shape": "disk",
                            "r": 1,
                            "cx": 1,
                            "cy": 1,
                            }
                        }
                }
            )

    # second connect has one dataset and one analysis:
    async with websockets.connect(ws_url) as ws:
        initial_msg = json.loads(await ws.recv())
        assert initial_msg['messageType'] == "INITIAL_STATE"
        assert initial_msg['status'] == "ok"
        assert len(initial_msg['datasets']) == 1
        assert len(initial_msg['analyses']) == 1
        assert initial_msg["analyses"][0]["details"]["parameters"] == {
            "roi": {
                "shape": "disk",
                "r": 1,
                "cx": 1,
                "cy": 1,
            },
        }
