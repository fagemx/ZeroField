"""Explicit synthetic fixed-price fixtures, never real provider pricing/billing."""
import datetime as dt
import os
from unittest.mock import patch
from project_assistant import execution_governance as governance, agent_console_store as resources


def authorize_synthetic_media(test):
    environment = resources.get_resource(test.conn,test.me,test.slug,'environment','env_local_4090')
    resources.save_resource(test.conn,test.me,test.slug,'environment',{'env_key':'env_local_4090',
        'version':environment['version'],'network_access':'full'})
    test.conn.commit()
    def quote(card, digest):
        return governance.trusted_quote(amount_usd='.0100',operation_digest=digest,
            expires_at=governance.cp.now()+dt.timedelta(minutes=5),provenance='synthetic_fixed_price_fixture_not_billing',hard_bound=True)
    quotes=patch.dict(governance._QUOTE_PROVIDERS,{driver:quote for driver in ('vendor_api','runninghub_cloud','comfy_partner','comfy_local')})
    quotes.start();test.addCleanup(quotes.stop)
    env=patch.dict(os.environ,{'OPENBENCH_AGENT_KEY_ENVS':','.join(filter(None,[os.environ.get('OPENBENCH_AGENT_KEY_ENVS',''),'SEEDANCE_API_KEY','RUNNINGHUB_API_KEY','COMFY_API_KEY','COMFY_ROUTER_TOKEN']))})
    env.start();test.addCleanup(env.stop)
