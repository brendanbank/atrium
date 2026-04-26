import { useEffect, useRef, useState } from 'react';

import { useAppConfig } from '@/hooks/useAppConfig';

interface Props {
  onToken: (token: string) => void;
}

const SCRIPT_ATTR = 'data-atrium-captcha-script';
// Globally unique window callback names per mount — multiple
// CaptchaWidget instances on the same page (e.g. login + a modal) must
// not stomp each other.
let _callbackSeq = 0;

interface WindowWithCallbacks extends Window {
  [key: string]: unknown;
}

function ensureScript(provider: 'turnstile' | 'hcaptcha'): void {
  const existing = document.querySelector(`script[${SCRIPT_ATTR}="${provider}"]`);
  if (existing) return;
  const url =
    provider === 'turnstile'
      ? 'https://challenges.cloudflare.com/turnstile/v0/api.js'
      : 'https://hcaptcha.com/1/api.js';
  const s = document.createElement('script');
  s.src = url;
  s.async = true;
  s.defer = true;
  s.setAttribute(SCRIPT_ATTR, provider);
  document.head.appendChild(s);
}

function nextCallbackName(): string {
  _callbackSeq += 1;
  return `__atriumCaptchaCb_${_callbackSeq}`;
}

export function CaptchaWidget({ onToken }: Props) {
  const { data } = useAppConfig();
  const provider = data?.auth?.captcha_provider ?? 'none';
  const siteKey = data?.auth?.captcha_site_key ?? null;

  // Stable per-mount callback name. ``useState`` (vs ``useRef``)
  // is the React-blessed pattern for "compute once, freeze for the
  // lifetime of the component".
  const [callbackName] = useState<string>(nextCallbackName);

  // Keep the latest onToken accessible to the window callback. We
  // can't read it inline in the effect closure or React-Compiler
  // would freeze the captured value — assigning via the effect
  // keeps the rule-of-refs lint happy.
  const onTokenRef = useRef(onToken);
  useEffect(() => {
    onTokenRef.current = onToken;
  }, [onToken]);

  useEffect(() => {
    if (provider === 'none' || !siteKey) return;
    ensureScript(provider);

    const w = window as unknown as WindowWithCallbacks;
    w[callbackName] = (token: string) => {
      onTokenRef.current(token);
    };

    return () => {
      delete w[callbackName];
    };
    // The provider script tag itself is left attached on unmount —
    // the providers do not support clean teardown, and a remount
    // (e.g. nav back to /login) would refetch the script otherwise.
  }, [provider, siteKey, callbackName]);

  if (provider === 'none' || !siteKey) {
    return null;
  }

  if (provider === 'turnstile') {
    return (
      <div
        className="cf-turnstile"
        data-sitekey={siteKey}
        data-callback={callbackName}
      />
    );
  }

  // hCaptcha
  return (
    <div
      className="h-captcha"
      data-sitekey={siteKey}
      data-callback={callbackName}
    />
  );
}
