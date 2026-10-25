"""Run the real supervisor with diagnostics against disposable fixture data only."""
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from test_backend_service import BACKEND, fixture

sys.path.insert(0, str(BACKEND))
from service import Supervisor


def main():
    os.environ['MNEMOSYNE_NO_EMBEDDINGS'] = '1'
    original = subprocess.Popen

    def diagnostic_child(*args, **kwargs):
        # Only children of this fresh fixture inherit diagnostic stderr. Never
        # accept an installed data directory or change production error output.
        if kwargs.get('stderr') == subprocess.DEVNULL:
            kwargs['stderr'] = sys.stderr
        command = list(args[0])
        host = str(BACKEND / 'host.py')
        if host in command:
            index = command.index(host)
            command[index:index + 1] = ['-c',
                'import faulthandler,runpy,sys; '
                'faulthandler.dump_traceback_later(10,repeat=True); '
                'sys.path.insert(0,sys.argv.pop(1)); '
                'sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name="__main__")',
                str(BACKEND), host]
            args = (command, *args[1:])
        return original(*args, **kwargs)

    with tempfile.TemporaryDirectory(prefix='desktop startup fixture ') as temporary:
        base = Path(temporary).resolve()
        app = base / 'reviewed application'
        fixture(app)
        with patch('subprocess.Popen', diagnostic_child):
            faulthandler.dump_traceback_later(10, repeat=True)
            supervisor = Supervisor(app, base / 'isolated data')
            try:
                assert supervisor.ready
                print('Isolated desktop startup succeeded', flush=True)
            finally:
                supervisor.close()
                faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    main()
