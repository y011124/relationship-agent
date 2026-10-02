"""Bounded academic search. Provider credentials never enter model context or traces."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import copy
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

NAMES = ('Google Scholar', 'Semantic Scholar', 'OpenAlex')


def safe_url(value):
    if not isinstance(value, str):
        return ''
    try:
        p = urlsplit(value)
        return value if p.scheme == 'https' and p.hostname and not p.username and not p.password else ''
    except ValueError:
        return ''


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url, headers):
    req = urllib.request.Request(url, headers={'User-Agent': 'ylune-academic/1.0', **headers})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('response too large')
    return json.loads(raw)


def abstract_text(index):
    if not isinstance(index, dict):
        return ''
    words = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and 0 <= position < 300:
                words[position] = str(word)
    return ' '.join(words[i] for i in sorted(words))


class AcademicSearch:
    def __init__(self, transport=None):
        self.keys = {name: os.getenv(env, '') for name, env in
                     [('serpapi', 'SERPAPI_API_KEY'), ('semantic', 'SEMANTIC_SCHOLAR_API_KEY'), ('openalex', 'OPENALEX_API_KEY')]}
        self.transport = transport or get_json
        self.cache = {}

    def configure(self, values):
        if not isinstance(values, dict) or set(values) - set(self.keys):
            raise ValueError('Invalid academic settings')
        if any(not isinstance(v, str) or len(v) > 2000 for v in values.values()):
            raise ValueError('Invalid academic key')
        for key, value in values.items():
            if value.strip():
                self.keys[key] = value.strip()
        self.cache.clear()

    def public_config(self):
        return {name: bool(key) for name, key in self.keys.items()}

    def _provider(self, name, query):
        if name == 'Google Scholar' and not self.keys['serpapi']:
            return [], {'provider': name, 'status': 'not_configured', 'count': 0}
        try:
            headers = {}
            if name == 'Google Scholar':
                url = 'https://serpapi.com/search.json?' + urlencode({'engine': 'google_scholar', 'q': query, 'num': 3, 'api_key': self.keys['serpapi']})
            elif name == 'Semantic Scholar':
                url = 'https://api.semanticscholar.org/graph/v1/paper/search?' + urlencode({'query': query, 'limit': 3, 'fields': 'title,year,authors,abstract,url,externalIds'})
                if self.keys['semantic']:
                    headers['x-api-key'] = self.keys['semantic']
            else:
                url = 'https://api.openalex.org/works?' + urlencode({'search': query, 'per-page': 3, 'select': 'id,title,publication_year,doi,authorships,abstract_inverted_index,primary_location'})
                if self.keys['openalex']:
                    headers['Authorization'] = 'Bearer ' + self.keys['openalex']
            data = self.transport(url, headers)
            if not isinstance(data, dict) or data.get('error'):
                raise ValueError('provider error')
            field = {'Google Scholar': 'organic_results', 'Semantic Scholar': 'data', 'OpenAlex': 'results'}[name]
            if field not in data and name == 'Google Scholar' and data.get('search_information', {}).get('total_results') == 0:
                data[field] = []
            if not isinstance(data.get(field), list):
                raise ValueError('unexpected response')
            docs = []
            for item in data[field][:3]:
                title = str(item.get('title') or '')[:350]
                if not title:
                    continue
                if name == 'Google Scholar':
                    text = str(item.get('snippet') or '')[:1000]
                    link, year, doi = item.get('link'), None, ''
                    authors = [x.get('name', '') for x in item.get('publication_info', {}).get('authors', [])][:5]
                    level = 'search_snippet' if text else 'metadata_only'
                elif name == 'Semantic Scholar':
                    text = str(item.get('abstract') or '')[:1000]
                    link, year = item.get('url'), item.get('year')
                    doi = str((item.get('externalIds') or {}).get('DOI') or '')
                    authors = [x.get('name', '') for x in item.get('authors', [])][:5]
                    level = 'abstract' if text else 'metadata_only'
                else:
                    text = abstract_text(item.get('abstract_inverted_index'))[:1000]
                    link = (item.get('primary_location') or {}).get('landing_page_url') or item.get('doi') or item.get('id')
                    year, doi = item.get('publication_year'), str(item.get('doi') or '').removeprefix('https://doi.org/')
                    authors = [(x.get('author') or {}).get('display_name', '') for x in item.get('authorships', [])][:5]
                    level = 'abstract' if text else 'metadata_only'
                docs.append({'title': title, 'source': name, 'text': text, 'url': safe_url(link),
                             'year': year if isinstance(year, int) else None, 'doi': doi[:200],
                             'authors': authors, 'evidence_level': level, 'found_in': [name]})
            return docs, {'provider': name, 'status': 'ok' if docs else 'empty', 'count': len(docs)}
        except urllib.error.HTTPError as exc:
            status = 'rate_limited' if exc.code == 429 else 'auth_required' if exc.code in (401, 403) else 'unavailable'
            exc.close()
        except (TimeoutError, OSError):
            status = 'unavailable'
        except (ValueError, TypeError, AttributeError, KeyError):
            status = 'invalid_response'
        return [], {'provider': name, 'status': status, 'count': 0}

    def search(self, query, enabled=True):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300:
            raise ValueError('Search query must contain 1-300 characters')
        query = query.strip()
        if not enabled:
            return {'query': query, 'documents': [], 'providers': [{'provider': n, 'status': 'demo_disabled', 'count': 0} for n in NAMES], 'cached': False}
        cached = self.cache.get(query)
        if cached and time.monotonic() - cached[0] < 900:
            result = copy.deepcopy(cached[1]); result['cached'] = True
            return result
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda n: self._provider(n, query), NAMES))
        docs, seen = [], {}
        # Round-robin keeps each available provider represented within the context budget.
        for position in range(3):
            for papers, _ in results:
                if position >= len(papers):
                    continue
                doc = papers[position]
                aliases = ['title:' + re.sub(r'\W+', '', doc['title'].lower())]
                if doc['doi']:
                    aliases.append('doi:' + doc['doi'].lower())
                existing = next((seen[a] for a in aliases if a in seen), None)
                if existing is not None:
                    current = docs[existing]
                    providers = list(dict.fromkeys(current['found_in'] + doc['found_in']))
                    if doc['evidence_level'] == 'abstract' and current['evidence_level'] != 'abstract':
                        current.update(doc)
                    current['found_in'] = providers
                    for alias in aliases:
                        seen[alias] = existing
                elif len(docs) < 6:
                    for alias in aliases:
                        seen[alias] = len(docs)
                    docs.append(doc)
        for i, doc in enumerate(docs):
            doc['id'] = 'paper-' + str(i + 1)
        result = {'query': query, 'documents': docs, 'providers': [s for _, s in results],
                  'cached': False, 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        if all(s['status'] in ('ok', 'empty', 'not_configured') for s in result['providers']):
            if len(self.cache) >= 100:
                self.cache.pop(next(iter(self.cache)))
            self.cache[query] = (time.monotonic(), copy.deepcopy(result))
        return result
