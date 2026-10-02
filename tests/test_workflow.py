import json
from pathlib import Path


def test_workflow_topology_and_stable_retry_payload():
    workflow=json.loads((Path(__file__).parents[1]/'n8n/workflows/kooki_chat.json').read_text(encoding='utf-8'))
    nodes={n['name']:n for n in workflow['nodes']}
    assert len(nodes)==len(workflow['nodes'])==17
    assert workflow['active'] is False
    assert all(n['type'].startswith('n8n-nodes-base.') for n in nodes.values())
    assert all('credentials' not in n for n in nodes.values())
    for source,connections in workflow['connections'].items():
        assert source in nodes
        for outputs in connections['main']:
            for edge in outputs:
                assert edge['node'] in nodes
    http=[n for n in nodes.values() if n['type']=='n8n-nodes-base.httpRequest']
    assert len(http)==3
    assert len({n['parameters']['jsonBody'] for n in http})==1
    assert all('Set Execution Context' in n['parameters']['jsonBody'] for n in http)
    assert all(n['retryOnFail'] is False for n in http)
    waits=[n for n in nodes.values() if n['type']=='n8n-nodes-base.wait']
    assert sorted(n['parameters']['amount'] for n in waits)==[2,4]
    seen=set()
    visiting=set()
    def visit(name):
        assert name not in visiting, 'Workflow retries must be bounded, with no cycle'
        if name in seen: return
        visiting.add(name)
        for outputs in workflow['connections'].get(name,{}).get('main',[]):
            for edge in outputs: visit(edge['node'])
        visiting.remove(name); seen.add(name)
    visit('Webhook - Chat Input')
    assert seen==set(nodes)
