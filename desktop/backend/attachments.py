"""Resolve a managed attachment for a native user action without loading models."""
import importlib.util
from pathlib import Path
from paths import reject_links


def attachment_path(root, record_id, attachment_id):
    root = Path(root)
    source = reject_links(root / 'app' / 'attachment_files.py')
    spec = importlib.util.spec_from_file_location('desktop_attachment_files', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    resources = root / 'state' / 'resources'
    file = module.resolve_attachment(root / 'state/data/mnemosyne.db', resources, record_id, attachment_id)
    return {'path': str(file), 'resources': str(resources.resolve())}
