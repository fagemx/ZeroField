import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { t } from '../i18n/index.js';
import { useLocale } from '../i18n/react.jsx';
import { pauseLine } from '../agentConsole/opsModel.js';

// SPEC_20 R40 on the Agent Board: one line while the Console's automation switch is off. It reads the
// switch only (any member may); crew readiness is untouched.
export function AutomationPausedNote({ slug }) {
  useLocale();
  const [automation, setAutomation] = useState(null);
  useEffect(() => {
    if (!slug) return undefined;
    let live = true;
    const load = () => api.get(`/projects/api/${slug}/agent-console/automation`).then(result => { if (live) setAutomation(result.automation); }).catch(() => {});
    load();
    const timer = setInterval(load, 60000);
    return () => { live = false; clearInterval(timer); };
  }, [slug]);
  if (!automation?.paused) return null;
  return <section className="crew-readiness automation-paused" role="status" aria-label={t('console.ops.automation.bannerTitle')}>
    <header><strong>{t('console.ops.automation.bannerTitle')}</strong></header>
    <p>{pauseLine(automation)} {t('console.ops.automation.scope')}</p>
  </section>;
}
