// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest';

import { isServerRoute, sanitizeRedirect } from './redirect';

describe('sanitizeRedirect', () => {
  it('returns null for nullish / empty values', () => {
    expect(sanitizeRedirect(null)).toBeNull();
    expect(sanitizeRedirect(undefined)).toBeNull();
    expect(sanitizeRedirect('')).toBeNull();
  });

  it('accepts same-origin site-absolute paths', () => {
    expect(sanitizeRedirect('/')).toBe('/');
    expect(sanitizeRedirect('/dashboard')).toBe('/dashboard');
    expect(sanitizeRedirect('/oauth/authorize?client_id=x&state=y')).toBe(
      '/oauth/authorize?client_id=x&state=y',
    );
    expect(sanitizeRedirect('/foo#frag')).toBe('/foo#frag');
  });

  it('rejects protocol-relative URLs', () => {
    expect(sanitizeRedirect('//evil.example')).toBeNull();
    expect(sanitizeRedirect('//evil.example/path')).toBeNull();
  });

  it('rejects absolute URLs with a scheme', () => {
    expect(sanitizeRedirect('https://evil.example')).toBeNull();
    expect(sanitizeRedirect('http://evil.example')).toBeNull();
    expect(sanitizeRedirect('javascript:alert(1)')).toBeNull();
    expect(sanitizeRedirect('data:text/html,<script>')).toBeNull();
  });

  it('rejects relative paths without leading slash', () => {
    expect(sanitizeRedirect('foo')).toBeNull();
    expect(sanitizeRedirect('./foo')).toBeNull();
    expect(sanitizeRedirect('../foo')).toBeNull();
  });

  it('preserves the inner redirect_uri when it contains a full URL', () => {
    // atrium-pa's /oauth/authorize bounces to /login?from=<encoded
    // authorize URL>, where the encoded URL itself contains a
    // redirect_uri=https://claude.ai/... query value. The from-VALUE
    // (after URL-decoding) starts with `/oauth/authorize` so it's a
    // valid path; the inner https:// is just part of the query.
    const from =
      '/oauth/authorize?client_id=abc&redirect_uri=https://claude.ai/cb';
    expect(sanitizeRedirect(from)).toBe(from);
  });
});

describe('isServerRoute', () => {
  it('recognises known server prefixes', () => {
    expect(isServerRoute('/oauth/authorize')).toBe(true);
    expect(isServerRoute('/oauth/authorize?client_id=x')).toBe(true);
    expect(isServerRoute('/api/users/me')).toBe(true);
    expect(isServerRoute('/.well-known/oauth-authorization-server')).toBe(true);
  });

  it('treats bare prefix segments as server routes too', () => {
    expect(isServerRoute('/oauth')).toBe(true);
    expect(isServerRoute('/api')).toBe(true);
    expect(isServerRoute('/.well-known')).toBe(true);
  });

  it('treats SPA routes as non-server', () => {
    expect(isServerRoute('/')).toBe(false);
    expect(isServerRoute('/admin')).toBe(false);
    expect(isServerRoute('/admin/audit')).toBe(false);
    expect(isServerRoute('/profile')).toBe(false);
    expect(isServerRoute('/2fa?from=%2F')).toBe(false);
  });

  it('does not match unrelated paths that merely contain the prefix', () => {
    // /apiary is not /api/* — should resolve as an SPA route.
    expect(isServerRoute('/apiary')).toBe(false);
    expect(isServerRoute('/oauthorize')).toBe(false);
  });
});
