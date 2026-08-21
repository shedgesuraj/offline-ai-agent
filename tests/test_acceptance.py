import os
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app
from backend.config import WORKSPACE


def client(): return TestClient(app)

def login(c, username):
    r=c.post('/register',data={'username':username,'password':'secure123'})
    assert r.status_code in (200,303)
    r=c.post('/login',data={'username':username,'password':'secure123'},follow_redirects=False)
    assert r.status_code==303


def test_health_and_ollama_adapter():
    c=client(); d=c.get('/health').json()
    assert d['offline_first'] is True
    assert d['model']=='qwen2.5:7b'
    assert d['ollama'] in {'ready','ollama_online_model_missing','ollama_offline'}


def test_pages_render():
    c=client(); login(c,'pages_user_final')
    for path in ['/dashboard','/chat','/memory','/tasks','/tools','/activity','/settings','/profile']:
        r=c.get(path); assert r.status_code==200, (path,r.status_code)


def test_privacy_default_no_chat_persistence():
    c=client(); login(c,'privacy_user_final')
    r=c.post('/api/chat',data={'message':'list files'}); assert r.status_code==200
    assert 'bubble user' not in c.get('/chat').text
    r=c.post('/settings',data={'model':'qwen2.5:7b','offline':'1','auto_execute':'0','save_history':'1'},follow_redirects=False); assert r.status_code==303
    c.post('/api/chat',data={'message':'list files'})
    assert 'bubble user' in c.get('/chat').text
    c.post('/api/privacy/clear-history'); assert 'bubble user' not in c.get('/chat').text


def test_explicit_memory_and_delete():
    c=client(); login(c,'memory_user_final')
    r=c.post('/api/memory',data={'content':'test memory'}); mid=r.json()['id']; assert r.json()['ok']
    assert c.delete(f'/api/memory/{mid}').json()['ok']


def test_workspace_tools_and_traversal():
    c=client(); login(c,'tool_user_final')
    assert c.post('/api/chat',data={'message':'list files'}).json()['verified'] is True
    blocked=c.post('/api/chat',data={'message':'read file ../requirements.txt'}).json()
    assert blocked['verified'] is False


def test_python_approval_and_one_shot_approval():
    c=client(); login(c,'approval_user_final')
    r=c.post('/api/chat',data={'message':'run python: print(2+2)'}); d=r.json()
    assert d['approval_required'] is True and d['verified'] is False
    r=c.post('/api/chat',data={'message':'run python: print(2+2)','approve':'1'}); d=r.json()
    assert d['tool']=='run_python' and d['verified'] is True and '4' in d['response']


def test_restricted_python():
    c=client(); login(c,'restricted_python_final')
    r=c.post('/api/chat',data={'message':'run python: import os\nprint(os.getcwd())','approve':'1'}).json()
    assert r['verified'] is False and 'blocked' in r['response'].lower()


def test_terminal_approval_and_block():
    c=client(); login(c,'terminal_final')
    r=c.post('/api/chat',data={'message':'run terminal: echo hello'}).json()
    assert r['approval_required'] is True
    r=c.post('/api/chat',data={'message':'run terminal: echo hello','approve':'1'}).json()
    assert r['verified'] is True and 'hello' in r['response'].lower()
    r=c.post('/api/chat',data={'message':'run terminal: shutdown /s','approve':'1'}).json()
    assert r['verified'] is False


def test_settings_and_audit():
    c=client(); login(c,'settings_final')
    r=c.post('/settings',data={'model':'qwen2.5:7b','offline':'1','auto_execute':'0','save_history':'0'},follow_redirects=False)
    assert r.status_code==303
    assert c.get('/activity').status_code==200


def test_llm_real_if_available():
    # On a developer machine this proves the actual Ollama integration. In CI without Ollama it skips.
    import httpx
    try:
        tags=httpx.get('http://127.0.0.1:11434/api/tags',timeout=1).json()
    except Exception:
        return
    names=[m.get('name','') for m in tags.get('models',[])]
    if not any(n=='qwen2.5:7b' or n.startswith('qwen2.5:7b:') for n in names):
        return
    from backend.llm import LocalLLM
    out=LocalLLM('qwen2.5:7b').generate('Reply with exactly the word LOCAL.')
    assert out


def test_rag_index_and_retrieval(monkeypatch):
    c=client(); login(c,'rag_user_final')
    sample=WORKSPACE/'rag_note.txt'; sample.write_text('Project uses FastAPI and SQLite for an offline agent.', encoding='utf-8')
    try:
        r=c.post('/api/knowledge',data={'path':'rag_note.txt'}); assert r.status_code==200
        from backend.rag import retrieve
        items=retrieve('rag_user_final','SQLite offline agent')
        assert items and 'SQLite' in items[0]
    finally:
        sample.unlink(missing_ok=True)


def test_index_command_and_forget_memory():
    c=client(); login(c,'command_memory_final')
    sample=WORKSPACE/'index_cmd.txt'; sample.write_text('local RAG acceptance document', encoding='utf-8')
    try:
        r=c.post('/api/chat',data={'message':'index file index_cmd.txt'}).json()
        assert r['tool']=='index_file' and r['verified'] is True
        mid=c.post('/api/memory',data={'content':'temporary memory'}).json()['id']
        r=c.post('/api/chat',data={'message':f'forget memory {mid}'}).json()
        assert r['tool']=='memory' and r['verified'] is True
    finally:
        sample.unlink(missing_ok=True)


def test_write_file_requires_approval_and_verifies():
    c=client(); login(c,'write_file_final')
    r=c.post('/api/chat',data={'message':'write file generated.txt: hello'}).json()
    assert r['approval_required'] is True and r['verified'] is False
    r=c.post('/api/chat',data={'message':'write file generated.txt: hello','approve':'1'}).json()
    assert r['tool']=='write_file' and r['verified'] is True
    assert (WORKSPACE/'generated.txt').read_text()=='hello'
    (WORKSPACE/'generated.txt').unlink()


def test_python_sandbox_blocks_filesystem_bypass():
    c=client(); login(c,'sandbox_python_final')
    code="import builtins\nbuiltins.open('escape.txt','w').write('x')"
    r=c.post('/api/chat',data={'message':f'run python: {code}','approve':'1'}).json()
    assert r['verified'] is False
    assert not (WORKSPACE/'escape.txt').exists()


def test_terminal_allowlist_blocks_shell_escape():
    c=client(); login(c,'sandbox_terminal_final')
    for command in ['echo hello && echo bad','cmd /c dir','python -c print(1)','echo ../requirements.txt']:
        r=c.post('/api/chat',data={'message':f'run terminal: {command}','approve':'1'}).json()
        assert r['verified'] is False


def test_sandbox_timeout():
    from backend.tools import run_python
    result=run_python('while True: pass', timeout=1)
    assert result['returncode']==124
