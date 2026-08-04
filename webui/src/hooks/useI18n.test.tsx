// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useI18n } from './useI18n';
import * as i18nModule from '../i18n';

describe('useI18n', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('returns the current language', () => {
    vi.spyOn(i18nModule, 'getLang').mockReturnValue('zh');
    const { result } = renderHook(() => useI18n());
    expect(result.current.lang).toBe('zh');
  });

  it('returns the t function from i18n module', () => {
    const { result } = renderHook(() => useI18n());
    expect(result.current.t).toBe(i18nModule.t);
  });

  it('calls setLang when changeLang is invoked', () => {
    const spy = vi.spyOn(i18nModule, 'setLang').mockImplementation(() => {});
    const { result } = renderHook(() => useI18n());

    act(() => { result.current.setLang('ja'); });

    expect(spy).toHaveBeenCalledWith('ja');
  });

  it('exposes supportedLangs constant', () => {
    const { result } = renderHook(() => useI18n());
    expect(result.current.supportedLangs).toEqual(['en', 'zh', 'ja']);
  });

  it('setLang reference is stable across re-renders', () => {
    const { result, rerender } = renderHook(() => useI18n());
    const firstRef = result.current.setLang;
    rerender();
    expect(result.current.setLang).toBe(firstRef);
  });
});
