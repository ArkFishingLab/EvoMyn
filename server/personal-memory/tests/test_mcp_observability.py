import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


class ObserverTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'vendor/mcp_observability.py'
        self.assertTrue(path.is_file(), 'Protocol metadata observer is not implemented')
        spec = importlib.util.spec_from_file_location('observer_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'events.jsonl'
        self.now = 1000.0
        self.observer = module.Observer(self.path, clock=lambda: self.now, timer=lambda: self.now)

    def events(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def send(self, value, incoming):
        self.observer.observe(json.dumps(value), incoming)

    def test_call_results_track_time_without_arguments_or_response_content(self):
        self.observer.connected()
        self.send({'id': 1, 'method': 'tools/call', 'params': {'name': 'archive_search', 'arguments': {'query': 'PRIVATE_QUERY'}}}, True)
        self.now += 1.25
        self.send({'id': 1, 'result': {'content': [{'text': 'PRIVATE_RESULT'}]}}, False)
        result = self.events()[-1]
        self.assertEqual((result['kind'], result['tool'], result['status'], result['duration_ms']), ('call_finished', 'archive_search', 'success', 1250))
        raw = self.path.read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE_QUERY', raw)
        self.assertNotIn('PRIVATE_RESULT', raw)

    def test_tool_and_protocol_errors_are_recorded_without_error_messages(self):
        for ident, response in [(1, {'result': {'isError': True, 'content': [{'text': 'SECRET_ERROR'}]}}), (2, {'error': {'message': 'SECRET_ERROR'}})]:
            self.send({'id': ident, 'method': 'tools/call', 'params': {'name': 'planner_create'}}, True)
            self.send(dict(id=ident, **response), False)
            self.assertEqual(self.events()[-1]['status'], 'error')
        self.assertNotIn('SECRET_ERROR', self.path.read_text(encoding='utf-8'))

    def test_disconnect_closes_pending_calls_and_does_not_invent_success(self):
        self.send({'id': 'x', 'method': 'tools/call', 'params': {'name': 'archive_record'}}, True)
        self.observer.disconnected()
        self.assertEqual(self.events()[-2]['status'], 'interrupted')
        self.assertEqual(self.events()[-1]['kind'], 'disconnected')

    def test_discovery_keeps_only_valid_names_and_malformed_messages_are_ignored(self):
        self.observer.observe('not json', True)
        self.send({'result': {'tools': [{'name': 'archive_get'}, {'name': 'https://secret.invalid/token'}]}}, False)
        self.assertEqual(self.events()[-1]['tools'], ['archive_get'])
        self.assertNotIn('secret.invalid', self.path.read_text(encoding='utf-8'))

    def test_string_and_integer_request_ids_do_not_collide(self):
        for ident, name in [(1, 'archive_get'), ('1', 'planner_get')]:
            self.send({'id': ident, 'method': 'tools/call', 'params': {'name': name}}, True)
        self.send({'id': 1, 'result': {}}, False)
        self.send({'id': '1', 'result': {}}, False)
        self.assertEqual([event['tool'] for event in self.events() if event['kind'] == 'call_finished'], ['archive_get', 'planner_get'])

    def test_current_state_survives_history_rotation(self):
        self.observer.max_bytes = 400
        self.observer.connected()
        self.send({'result': {'tools': [{'name': 'archive_get'}]}}, False)
        for ident in range(20):
            self.send({'id': ident, 'method': 'tools/call', 'params': {'name': 'archive_get'}}, True)
            self.send({'id': ident, 'result': {}}, False)
        state = json.loads(self.path.with_suffix('.state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['lifecycle'], 'connected')
        self.assertEqual(state['session'], self.observer.session)
        self.assertEqual(state['tools'], ['archive_get'])
        self.observer.disconnected()
        state = json.loads(self.path.with_suffix('.state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['lifecycle'], 'disconnected')


if __name__ == '__main__':
    unittest.main()
