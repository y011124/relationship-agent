"""Offline provider fixtures and evidence workflow integration; no external quota."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from relationship_agent.academic import AcademicSearch, safe_url, abstract_text
from relationship_agent.demo import MockModelClient
from relationship_agent.engine import RelationshipAgent
from relationship_agent.routing import demo_route
from relationship_agent.schemas import ContractError, validate_stage
from relationship_agent.storage import Store


def fixture(url, headers):
    if 'serpapi.com' in url:
        return {'organic_results': [{'title': 'Attachment research', 'link': 'https://example.org/paper', 'snippet': 'Search excerpt.'}]}
    if 'semanticscholar.org' in url:
        return {'data': [{'title': 'Attachment research', 'url': 'https://example.org/paper', 'year': 2020,
                          'abstract': 'Attachment patterns were studied in couples.', 'externalIds': {'DOI': '10.1/a'}, 'authors': [{'name': 'Researcher'}]}]}
    return {'results': [{'title': 'Other study', 'id': 'https://openalex.org/W123', 'doi': 'https://doi.org/10.1/b',
                         'publication_year': 2021, 'abstract_inverted_index': {'Evidence': [0], 'is': [1], 'limited.': [2]}}]}


class AcademicTests(unittest.TestCase):
    def service(self, transport=fixture):
        s = AcademicSearch(transport)
        s.keys = dict(serpapi='test-secret', semantic='', openalex='')
        return s

    def test_provider_normalization_dedup_and_stronger_excerpt(self):
        result = self.service().search('attachment')
        self.assertEqual(len(result['documents']), 2)
        doc = result['documents'][0]
        self.assertEqual(doc['evidence_level'], 'abstract')
        self.assertEqual(doc['found_in'], ['Google Scholar', 'Semantic Scholar'])
        self.assertEqual(doc['year'], 2020)
        self.assertEqual(result['documents'][1]['text'], 'Evidence is limited.')
        self.assertNotIn('test-secret', json.dumps(result))

    def test_api_parameters_and_separate_credentials(self):
        calls = []
        def transport(url, headers):
            calls.append((url, headers)); return fixture(url, headers)
        s = self.service(transport)
        s.configure({'semantic': 's2-secret', 'openalex': 'oa-secret'})
        s.search('attachment')
        for url, headers in calls:
            host = urlsplit(url).hostname
            if host == 'serpapi.com':
                self.assertEqual(parse_qs(urlsplit(url).query)['engine'], ['google_scholar'])
                self.assertEqual(headers, {})
            elif host == 'api.semanticscholar.org':
                self.assertEqual(headers, {'x-api-key': 's2-secret'})
                self.assertNotIn('test-secret', url)
            else:
                self.assertEqual(headers, {'Authorization': 'Bearer oa-secret'})
        self.assertEqual(s.public_config(), {'serpapi': True, 'semantic': True, 'openalex': True})

    def test_missing_key_and_rate_limit_do_not_block_openalex(self):
        def transport(url, headers):
            if 'semanticscholar' in url:
                raise urllib.error.HTTPError(url, 429, 'secret must not leak', {}, None)
            self.assertNotIn('serpapi', url)
            return fixture(url, headers)
        s = self.service(transport); s.keys['serpapi'] = ''
        r = s.search('attachment')
        self.assertEqual([p['status'] for p in r['providers']], ['not_configured', 'rate_limited', 'ok'])
        self.assertEqual(len(r['documents']), 1)
        self.assertNotIn('secret must not leak', json.dumps(r))

    def test_cache_and_demo_do_not_repeat_network_calls(self):
        calls = []
        def transport(url, headers):
            calls.append(url); return fixture(url, headers)
        s = self.service(transport)
        self.assertEqual(s.search('attachment', enabled=False)['documents'], [])
        self.assertEqual(len(calls), 0)
        s.search('attachment'); result = s.search('attachment')
        self.assertTrue(result['cached']); self.assertEqual(len(calls), 3)
        result['documents'].clear()
        self.assertEqual(len(s.search('attachment')['documents']), 2)

    def test_invalid_response_and_no_results_are_distinct(self):
        r = self.service(lambda *a: {}).search('attachment')
        self.assertTrue(all(s['status'] == 'invalid_response' for s in r['providers']))
        r = self.service(lambda *a: {'organic_results': [], 'data': [], 'results': []}).search('attachment')
        self.assertTrue(all(s['status'] == 'empty' for s in r['providers']))

    def test_url_and_query_boundaries(self):
        for url in ['javascript:alert(1)', 'https://user:secret@example.org', 'file:///tmp/a']:
            self.assertEqual(safe_url(url), '')
        self.assertEqual(abstract_text({'hello': [999999999]}), '')
        for query in ['email@example.com', 'https://private.example', '1234567890']:
            with self.assertRaises(ContractError):
                validate_stage('academic_query', {'query': query}, {})

    def test_explicit_sources_and_no_search_intents(self):
        self.assertEqual(demo_route('给我一些依恋相关论文')['intent'], 'evidence')
        self.assertEqual(demo_route('不要搜索，解释依恋')['intent'], 'knowledge')
        self.assertEqual(demo_route('我难过，只想聊聊')['intent'], 'chat')

    def test_workflow_resume_preserves_search_and_verified_links(self):
        class Client(MockModelClient):
            def __init__(self):
                self.mode = 'api'; self.failed = False
            def complete_json(self, stage, payload, schema=None):
                if stage == 'knowledge' and not self.failed:
                    self.failed = True
                    raise RuntimeError('interrupt after retrieval')
                return super().complete_json(stage, payload, schema)
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def transport(url, headers):
                calls.append(url); return fixture(url, headers)
            s = self.service(transport)
            store = Store(root); client = Client()
            sid = store.create_session('test', 'api')['id']
            agent = RelationshipAgent(client, store, s)
            rid = agent.start(sid, '给我依恋相关论文', 'auto')
            with self.assertRaises(RuntimeError):
                agent.execute(rid)
            self.assertEqual(len(calls), 3)
            result = agent.execute(rid)
            self.assertEqual(len(calls), 3)
            self.assertEqual(result['kind'], 'evidence')
            self.assertEqual(result['sources'][0]['url'], 'https://example.org/paper')
            self.assertEqual(store.context(sid), [])
            self.assertNotIn('test-secret', json.dumps(store.run(rid)))

    def test_metadata_only_does_not_generate_scientific_claims(self):
        class Client(MockModelClient):
            def __init__(self): self.mode = 'api'
            def complete_json(self, stage, payload, schema=None):
                self_test.assertNotEqual(stage, 'knowledge')
                return super().complete_json(stage, payload, schema)
        self_test = self
        with tempfile.TemporaryDirectory() as root:
            s = self.service(lambda *a: {'organic_results': [{'title': 'Title only'}], 'data': [], 'results': []})
            store = Store(root); sid = store.create_session('test', 'api')['id']
            agent = RelationshipAgent(Client(), store, s)
            result = agent.execute(agent.start(sid, '依恋相关论文', 'auto'))
            self.assertEqual(result['sources'], [])
            self.assertEqual(result['academic_search']['documents'][0]['evidence_level'], 'metadata_only')


if __name__ == '__main__':
    unittest.main()
