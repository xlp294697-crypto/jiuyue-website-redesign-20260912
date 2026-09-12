'use strict';
(()=>{
const consentKey = 'jiuyueAnalyticsConsent';
const consentAtKey = 'jiuyueAnalyticsConsentAt';
const consentVersionKey = 'jiuyueAnalyticsConsentVersion';
const analyticsNoticeVersion = '2026-08-22';
const visitorKey = 'jiuyueVisitor';
const query = new URLSearchParams(location.search);
const consentPanel = document.querySelector('#analytics-consent');
const analyticsSettings = document.querySelector('#analytics-settings');
let analyticsStarted = false;
let visitorId = '';
let sectionObserver = null;

function getConsent() {
  try {
    return localStorage.getItem(consentKey) || '';
  } catch {
    return '';
  }
}

function setConsent(value) {
  try {
    if (value) localStorage.setItem(consentKey, value);
    else localStorage.removeItem(consentKey);
  } catch {}
}

function getConsentAt() {
  try {
    return localStorage.getItem(consentAtKey) || '';
  } catch {
    return '';
  }
}

function setConsentAt(value) {
  try {
    if (value) localStorage.setItem(consentAtKey, value);
    else localStorage.removeItem(consentAtKey);
  } catch {}
}

function getConsentVersion() {
  try {
    return localStorage.getItem(consentVersionKey) || '';
  } catch {
    return '';
  }
}

function setConsentVersion(value) {
  try {
    if (value) localStorage.setItem(consentVersionKey, value);
    else localStorage.removeItem(consentVersionKey);
  } catch {}
}

function hasAnalyticsConsent() {
  return (
    getConsent() === 'yes' &&
    getConsentVersion() === analyticsNoticeVersion &&
    Boolean(getConsentAt())
  );
}

function newVisitorId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return [...bytes]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');
}

function getVisitorId() {
  if (visitorId) return visitorId;
  try {
    visitorId = localStorage.getItem(visitorKey) || '';
    if (!visitorId) {
      visitorId = newVisitorId();
      localStorage.setItem(visitorKey, visitorId);
    }
  } catch {
    visitorId = newVisitorId();
  }
  return visitorId;
}

function campaignContext() {
  const clean = (name, maximum) =>
    (query.get(name) || '')
      .normalize('NFKC')
      .replace(/[^\p{L}\p{N}._-]+/gu, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, maximum);
  return {
    source: clean('utm_source', 40),
    medium: clean('utm_medium', 40),
    campaign: clean('utm_campaign', 80),
  };
}

function referrerOrigin() {
  if (!document.referrer) return '';
  try {
    const parsed = new URL(document.referrer);
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.origin : '';
  } catch {
    return '';
  }
}

function eventContext() {
  return {
    page: location.pathname,
    visitorId: getVisitorId(),
    referrer: referrerOrigin(),
    utm: campaignContext(),
    device: innerWidth < 700 ? 'mobile' : 'desktop',
    analyticsConsent: true,
    analyticsNoticeVersion,
    analyticsConsentAt: getConsentAt(),
  };
}

async function request(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    let response;
    let data;
    try {
      response = await fetch(url, { ...options, signal: controller.signal });
      data = await response.json();
    } catch {
      throw new Error(
        controller.signal.aborted
          ? '请求超时，请稍后重试；预约可能已提交，请勿连续重复提交。'
          : '网络连接异常，请检查网络后重试。',
      );
    }
    if (!response.ok)
      throw new Error(data.error?.message || '提交失败，请稍后再试。');
    return data;
  } finally {
    clearTimeout(timeout);
  }
}

function track(eventType, details = {}) {
  if (!hasAnalyticsConsent()) return Promise.resolve();
  return request('/api/events', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ...eventContext(), eventType, ...details }),
  }).catch(() => {});
}

function startAnalytics() {
  if (analyticsStarted || !hasAnalyticsConsent()) return;
  analyticsStarted = true;
  track('page_view');
  if ('IntersectionObserver' in window) {
    const observed = new Set();
    sectionObserver = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          const section = entry.target.dataset.section;
          if (entry.isIntersecting && !observed.has(section)) {
            observed.add(section);
            track('section_view', { section });
            sectionObserver.unobserve(entry.target);
          }
        }),
      { threshold: 0.28 },
    );
    document
      .querySelectorAll('.observed-section')
      .forEach((section) => sectionObserver.observe(section));
  }
}

function openConsentSettings() {
  consentPanel.hidden = false;
  consentPanel.querySelector('[data-analytics-accept]').focus();
}

function closeConsentSettings() {
  consentPanel.hidden = true;
}

consentPanel
  .querySelector('[data-analytics-accept]')
  .addEventListener('click', () => {
    setConsent('yes');
    setConsentAt(new Date().toISOString());
    setConsentVersion(analyticsNoticeVersion);
    closeConsentSettings();
    startAnalytics();
  });
consentPanel
  .querySelector('[data-analytics-reject]')
  .addEventListener('click', () => {
    setConsent('no');
    setConsentAt('');
    setConsentVersion('');
    try {
      localStorage.removeItem(visitorKey);
    } catch {}
    visitorId = '';
    analyticsStarted = false;
    if (sectionObserver) sectionObserver.disconnect();
    sectionObserver = null;
    closeConsentSettings();
  });
analyticsSettings.addEventListener('click', openConsentSettings);
const savedConsent = getConsent();
if (
  !['yes', 'no'].includes(savedConsent) ||
  (savedConsent === 'yes' && !hasAnalyticsConsent())
) {
  setConsent('');
  setConsentAt('');
  setConsentVersion('');
  openConsentSettings();
} else startAnalytics();

document.querySelectorAll('[data-assessment-source]').forEach((link) =>
  link.addEventListener('click', () => {
    track('assessment_click', { section: link.dataset.assessmentSource });
  }),
);

window.jiuyueAnalytics={hasConsent:hasAnalyticsConsent,track,attribution:()=>({referrer:referrerOrigin(),utm:campaignContext(),analyticsNoticeVersion,analyticsConsentAt:getConsentAt()})};
document.querySelectorAll('a[href*="booking/"]').forEach(link=>link.addEventListener('click',()=>track('assessment_click',{section:'booking'})));

})();
