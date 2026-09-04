// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

export interface ComponentVersion {
  // Null when the host image stamped a version but no name — the UI
  // then labels the line with the brand name instead.
  name: string | null;
  // The git tag the image was built from. Null when the build wasn't
  // tagged — read `commit` instead.
  version: string | null;
  // Full commit sha of the build. Null on an image that predates the
  // build stamp, or a local build without the build args.
  commit: string | null;
}

export interface VersionInfo {
  atrium: ComponentVersion;
  // Null on a bare atrium deployment: there is no host app layer, so
  // the UI renders a single line.
  app: ComponentVersion | null;
}

export const VERSION_KEY = ['version'] as const;

/**
 * Build stamps of the running deployment. Authenticated-only on the
 * backend (an anonymous version string is a fingerprinting gift), so
 * only call this behind a signed-in gate.
 *
 * The values are baked into the image at build time and cannot change
 * while the process lives — hence no refetching at all.
 */
export function useVersionInfo(enabled = true) {
  return useQuery({
    queryKey: VERSION_KEY,
    queryFn: async () => (await api.get<VersionInfo>('/version')).data,
    enabled,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

/** How many sha characters the menu shows. Same width as `git log --oneline`. */
const SHORT_SHA = 7;

/**
 * The line as rendered in the menu, given the label to put in front:
 *
 *   Atrium v0.29.1        tagged build — the tag, verbatim
 *   atrium-pa: 22d2801    untagged build — the short commit
 *
 * The colon is the tell: a version follows the name directly, a
 * commit is introduced. Without it "atrium-pa 22d2801" reads like a
 * strange version number.
 *
 * Returns null when the image carries no stamp at all — there is
 * nothing to say, and a placeholder would be worse than no line.
 */
export function formatComponentVersion(
  label: string,
  component: ComponentVersion | null | undefined,
): string | null {
  if (!component) return null;
  if (component.version) return `${label} ${component.version}`;
  if (component.commit) return `${label}: ${component.commit.slice(0, SHORT_SHA)}`;
  return null;
}
