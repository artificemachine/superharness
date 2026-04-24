import socket
import json
from pathlib import Path
from superharness.engine.operator import Operator

def test_operator_arbitrates_conflicting_port(tmp_path):
    # Setup project structure
    project_dir = tmp_path / "port_proj"
    project_dir.mkdir()
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    (sh_dir / "handoffs").mkdir()
    
    # 1. Find any free port to use as our base
    import socket
    base_port = 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        base_port = s.getsockname()[1]

    # 2. Block that base port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", base_port))
        s.listen(1)
        
        # 3. Start the Operator stack pointing at the blocked port
        op = Operator(project_dir)
        op.start_stack(dashboard_port=base_port)
        
        # 4. Verify it chose base_port + 1 instead
        op_file = sh_dir / "operator-state.json"
        assert op_file.exists()

        info = json.loads(op_file.read_text())
        assert info["dashboard_port"] == base_port + 1
        
        # Cleanup
        op.stop_all()
