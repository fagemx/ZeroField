import { t as uiText } from '../i18n/index.js';

// SPEC_20 R12: the failure classes the server reports for a failed model call (model_client.FAILURE_CLASSES).
export const PROVIDER_FAILURES = ['local', 'quota', 'auth', 'provider', 'timeout', 'empty', 'output', 'gpu_busy'];
const KEYS = { gpu_busy: 'gpuBusy' };

// The plain-language line for a failure class, or '' when the value is not one (older rows keep their own text).
export function providerFailureText(kind) {
  return PROVIDER_FAILURES.includes(kind) ? uiText(`providerFailures.${KEYS[kind] || kind}`) : '';
}
