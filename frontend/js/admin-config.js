"use strict";
// Public identifiers only. Both local preview and CloudFront are registered callbacks.
window.ADMIN_CONFIG = Object.freeze({
  issuer: "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_ga4Llp0Ji",
  domain: "https://ccd-admin-707256068320.auth.ap-south-1.amazoncognito.com",
  clientId: "64tedsgkl2e5c7j6o87q2bdflv",
  sessionApiUrl: "https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin/session",
  issuanceApiUrl: "https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin/certificates",
  redirectUri: `${window.location.origin}/admin.html`,
  logoutUri: `${window.location.origin}/verify.html`
});
