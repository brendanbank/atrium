// Copyright (c) 2026 Brendan Bank
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef } from 'react';

/**
 * React wrapper around the CDN-loaded CKEditor 5 ClassicEditor build.
 *
 * The editor itself comes from cdn.ckeditor.com via <script> tags in
 * index.html — we don't import anything from npm so the deprecated
 * "predefined build" packages aren't in our tree. Config mirrors the
 * bcource/static/ckeditor.js setup.
 *
 * `value` is the HTML string; `onChange` fires whenever the editor's
 * content changes. Changes to `value` from the parent while the editor
 * is mounted are intentionally ignored — the editor owns its document
 * model, and pushing new data mid-edit would clobber the cursor.
 */

type ClassicEditorInstance = {
  setData: (data: string) => void;
  getData: () => string;
  destroy: () => Promise<void>;
  model: { document: { on: (evt: string, cb: () => void) => void } };
};

type CKEditorBundle = {
  ClassicEditor: {
    create: (
      el: HTMLElement,
      config: Record<string, unknown>,
    ) => Promise<ClassicEditorInstance>;
  };
  [plugin: string]: unknown;
};

declare global {
  interface Window {
    CKEDITOR?: CKEditorBundle;
    CKEDITOR_LICENSE_KEY?: string;
  }
}

const BASE_TOOLBAR = [
  'heading',
  '|',
  'fontSize',
  'fontColor',
  'fontBackgroundColor',
  '|',
  'bold',
  'italic',
  'underline',
  'strikethrough',
  'removeFormat',
  '|',
  'link',
  'bulletedList',
  'numberedList',
  '|',
  'outdent',
  'indent',
  'blockQuote',
  'insertTable',
  '|',
  'sourceEditing',
  'undo',
  'redo',
];

// Names must line up with what's actually on window.CKEDITOR. Missing
// plugins would crash ClassicEditor.create, so keep the list in
// lock-step with BASE_TOOLBAR.
const PLUGIN_NAMES = [
  'Alignment',
  'Autoformat',
  'AutoLink',
  'BlockQuote',
  'Bold',
  'Essentials',
  'FontBackgroundColor',
  'FontColor',
  'FontSize',
  'GeneralHtmlSupport',
  'Heading',
  'Indent',
  'IndentBlock',
  'Italic',
  'Link',
  'List',
  'Paragraph',
  'RemoveFormat',
  'SourceEditing',
  'Strikethrough',
  'Table',
  'TableToolbar',
  'TextTransformation',
  'Underline',
];

async function waitForCKEditor(): Promise<CKEditorBundle> {
  if (window.CKEDITOR) return window.CKEDITOR;
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = () => {
      if (window.CKEDITOR) return resolve(window.CKEDITOR);
      if (Date.now() - start > 10_000) {
        reject(new Error('CKEditor CDN script did not load within 10 s'));
        return;
      }
      setTimeout(tick, 50);
    };
    tick();
  });
}

interface Props {
  value: string;
  onChange: (html: string) => void;
  disabled?: boolean;
}

export function CKEditorField({ value, onChange, disabled }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<ClassicEditorInstance | null>(null);
  // Always call the latest onChange — avoids stale closures when the
  // parent re-renders with a new callback. Refs aren't reactive, so the
  // during-render assignment is intentional (the standard "latest
  // callback" pattern).
  const onChangeRef = useRef(onChange);
  // eslint-disable-next-line react-hooks/refs
  onChangeRef.current = onChange;
  // Same trick for the initial value: the parent often sets it in an
  // effect AFTER we've begun async editor init, so the closure below
  // would use the stale "" value. Reading via the ref at setData-time
  // picks up whatever's current when the editor is actually ready.
  const valueRef = useRef(value);
  // eslint-disable-next-line react-hooks/refs
  valueRef.current = value;

  useEffect(() => {
    let cancelled = false;
    // Track the editor this particular effect created, so cleanup can
    // destroy it even if the async create is still in flight. StrictMode
    // in dev mounts/unmounts/mounts again — without this, the first
    // mount's editor leaks into the second mount's host div and the
    // setData call races.
    let localEditor: ClassicEditorInstance | null = null;

    (async () => {
      const bundle = await waitForCKEditor().catch((err) => {
         
        console.error('CKEditor unavailable', err);
        return null;
      });
      if (!bundle || cancelled || !hostRef.current) return;

      const plugins = PLUGIN_NAMES.map((n) => bundle[n]).filter(Boolean);
      try {
        localEditor = await bundle.ClassicEditor.create(hostRef.current, {
          licenseKey: window.CKEDITOR_LICENSE_KEY || 'GPL',
          plugins,
          toolbar: { items: BASE_TOOLBAR, shouldNotGroupWhenFull: false },
          heading: {
            options: [
              { model: 'paragraph', title: 'Paragraph', class: 'ck-heading_paragraph' },
              { model: 'heading1', view: 'h1', title: 'Heading 1', class: 'ck-heading_heading1' },
              { model: 'heading2', view: 'h2', title: 'Heading 2', class: 'ck-heading_heading2' },
              { model: 'heading3', view: 'h3', title: 'Heading 3', class: 'ck-heading_heading3' },
            ],
          },
          htmlSupport: {
            allow: [{ name: /.*/, styles: true, attributes: true, classes: true }],
          },
          table: {
            contentToolbar: ['tableColumn', 'tableRow', 'mergeTableCells'],
          },
          link: {
            addTargetToExternalLinks: true,
            defaultProtocol: 'https://',
          },
        });
      } catch (err) {
        // StrictMode can trigger a second create on a host the first
        // one already owned — swallow so the UI stays usable.
         
        console.warn('CKEditor create failed', err);
        return;
      }

      if (cancelled) {
        await localEditor.destroy();
        return;
      }
      localEditor.setData(valueRef.current);
      localEditor.model.document.on('change:data', () => {
        if (localEditor) onChangeRef.current(localEditor.getData());
      });
      editorRef.current = localEditor;
    })();

    return () => {
      cancelled = true;
      if (editorRef.current) {
        void editorRef.current.destroy();
        editorRef.current = null;
      } else if (localEditor) {
        // Create resolved but the component unmounted before we could
        // publish it — destroy so the stale editor doesn't linger in
        // the host DOM for the next mount.
        void localEditor.destroy();
      }
    };
     
  }, []);

  return (
    <div
      ref={hostRef}
      aria-disabled={disabled}
      style={{ minHeight: 160 }}
    />
  );
}
