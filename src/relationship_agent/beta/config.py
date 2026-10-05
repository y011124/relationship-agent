from dataclasses import dataclass
import os
import math
from urllib.parse import urlsplit

@dataclass
class Settings:
    database_url: str = 'sqlite:///memory/persona.sqlite3'
    origin: str = 'http://127.0.0.1:8770'
    production: bool = False
    mode: str = 'mock'
    invite_code: str = ''
    workers: int = 2
    user_daily_calls: int = 40
    global_daily_calls: int = 200
    daily_budget_usd: float = 2.0
    request_reserve_usd: float = 0.05
    input_usd_per_million: float = 0.0
    output_usd_per_million: float = 0.0
    provider_label: str = '本地演示 / Local demo'
    privacy_contact: str = ''

    @classmethod
    def env(cls):
        return cls(database_url=os.getenv('DATABASE_URL', cls.database_url),
          origin=os.getenv('PERSONA_ORIGIN', cls.origin).rstrip('/'),
          production=os.getenv('PERSONA_ENV') == 'production', mode=os.getenv('PERSONA_MODE', 'mock'),
          invite_code=os.getenv('PERSONA_INVITE_CODE', ''), workers=int(os.getenv('PERSONA_WORKERS', '2')),
          user_daily_calls=int(os.getenv('PERSONA_USER_DAILY_CALLS', '40')),
          global_daily_calls=int(os.getenv('PERSONA_GLOBAL_DAILY_CALLS', '200')),
          daily_budget_usd=float(os.getenv('PERSONA_DAILY_BUDGET_USD', '2')),
          request_reserve_usd=float(os.getenv('PERSONA_REQUEST_RESERVE_USD', '.05')),
          input_usd_per_million=float(os.getenv('PERSONA_INPUT_USD_PER_MILLION', '0')),
          output_usd_per_million=float(os.getenv('PERSONA_OUTPUT_USD_PER_MILLION', '0')),
          provider_label=os.getenv('PERSONA_PROVIDER_LABEL', 'Local demo'),
          privacy_contact=os.getenv('PERSONA_PRIVACY_CONTACT', ''))

    def validate(self):
        p = urlsplit(self.origin)
        if p.scheme not in ('http', 'https') or not p.hostname or p.path or p.query or p.fragment or p.username or p.password:
            raise ValueError('PERSONA_ORIGIN must be an origin without a path')
        if self.mode not in ('mock', 'api') or not 1 <= self.workers <= 8:
            raise ValueError('Invalid mode or worker count')
        if min(self.user_daily_calls, self.global_daily_calls, self.daily_budget_usd, self.request_reserve_usd) <= 0:
            raise ValueError('Budgets must be positive')
        if not all(math.isfinite(x) and x >= 0 for x in (self.daily_budget_usd,self.request_reserve_usd,self.input_usd_per_million,self.output_usd_per_million)):
            raise ValueError('Budgets and prices must be finite nonnegative numbers')
        if self.production:
            if p.scheme != 'https' or not self.database_url.startswith(('postgresql:', 'postgresql+')):
                raise ValueError('Production requires HTTPS and PostgreSQL')
            if self.mode != 'api' or len(self.invite_code) < 16 or not self.privacy_contact:
                raise ValueError('Production requires API mode, a 16+ character invite code and privacy contact')
            if not os.getenv('GLM_API_KEY') and not os.getenv('PERSONA_API_KEY'):
                raise ValueError('Production model key is missing')
            if min(self.input_usd_per_million, self.output_usd_per_million) <= 0:
                raise ValueError('Configure current model prices before production')
            # 24k input characters plus a conservative 4x token allowance and 4096 output tokens.
            upper = (96000*self.input_usd_per_million + 4096*self.output_usd_per_million)/1e6
            if self.request_reserve_usd < upper:
                raise ValueError('Request reservation is below the configured conservative token allowance')
