---
title: Client Onboarding Intake Form — Stormfront Inc
outputs: [pdf]
pdf_forms: true
output_filename: "Stormfront-Onboarding-Intake-Form"
date: 1 April 2026
cover_page: false
---

{% include "company-header.md" %}

# Client Onboarding Intake Form

**Client:** {{ client }}
**Prepared by:** {{ account_manager }}
**Date:** {{ date }}

Please complete all sections below and return to {{ account_manager }} before your kickoff call.

---

## Contact Details

<div class="form-section">
<div class="form-row">
<div class="form-group">
<label>Primary Contact Name</label>
<input type="text" name="primary_contact_name" />
</div>
<div class="form-group">
<label>Title / Role</label>
<input type="text" name="primary_contact_role" />
</div>
</div>

<div class="form-row">
<div class="form-group">
<label>Email Address</label>
<input type="email" name="primary_contact_email" />
</div>
<div class="form-group">
<label>Phone</label>
<input type="tel" name="primary_contact_phone" />
</div>
</div>

<div class="form-row">
<div class="form-group">
<label>Technical Contact (if different)</label>
<input type="text" name="technical_contact_name" />
</div>
<div class="form-group">
<label>Technical Contact Email</label>
<input type="email" name="technical_contact_email" />
</div>
</div>
</div>

---

## Environment Details

<div class="form-section">
<div class="form-row">
<div class="form-group">
<label>Primary Cloud Provider</label>
<select name="cloud_provider">
<option value="">— Select —</option>
<option value="aws">AWS</option>
<option value="azure">Azure</option>
<option value="gcp">Google Cloud</option>
<option value="on-prem">On-Premises</option>
<option value="hybrid">Hybrid</option>
</select>
</div>
<div class="form-group">
<label>Estimated Active Users</label>
<select name="user_count">
<option value="">— Select —</option>
<option value="lt25">Less than 25</option>
<option value="25-100">25–100</option>
<option value="100-500">100–500</option>
<option value="500+">500+</option>
</select>
</div>
</div>

<div class="form-row">
<div class="form-group">
<label>Preferred SSO Method</label>
<select name="sso_method">
<option value="">— Select —</option>
<option value="saml">SAML 2.0</option>
<option value="oidc">OIDC / OAuth 2.0</option>
<option value="azure-ad">Azure Active Directory</option>
<option value="google">Google Workspace</option>
<option value="none">No SSO required</option>
</select>
</div>
<div class="form-group">
<label>Expected Go-Live Date</label>
<input type="text" name="go_live_date" />
</div>
</div>
</div>

---

## Products & Features

Which Blueshift products will you be activating? Check all that apply.

<div class="form-section">
<div class="checkbox-group">
<label class="checkbox-label"><input type="checkbox" name="product_nova" value="yes" /> Nova Analytics</label>
<label class="checkbox-label"><input type="checkbox" name="product_pulse" value="yes" /> Pulse Monitor</label>
<label class="checkbox-label"><input type="checkbox" name="product_flow" value="yes" /> Flow Automation</label>
<label class="checkbox-label"><input type="checkbox" name="product_arc" value="yes" /> Arc Reporting</label>
</div>
</div>

Which integrations do you require at launch?

<div class="form-section">
<div class="checkbox-group">
<label class="checkbox-label"><input type="checkbox" name="int_slack" value="yes" /> Slack</label>
<label class="checkbox-label"><input type="checkbox" name="int_pagerduty" value="yes" /> PagerDuty</label>
<label class="checkbox-label"><input type="checkbox" name="int_jira" value="yes" /> Jira</label>
<label class="checkbox-label"><input type="checkbox" name="int_datadog" value="yes" /> Datadog</label>
<label class="checkbox-label"><input type="checkbox" name="int_webhook" value="yes" /> Webhooks</label>
<label class="checkbox-label"><input type="checkbox" name="int_other" value="yes" /> Other</label>
</div>

<div class="form-row" style="margin-top: 4mm;">
<div class="form-group">
<label>Other Integrations (please specify)</label>
<input type="text" name="integrations_other" />
</div>
</div>
</div>

---

## Additional Notes

<div class="form-section">
<div class="section-note">Any specific requirements, constraints, or questions for the kickoff call?</div>
<textarea name="additional_notes"></textarea>
</div>

---

**Return completed form to:** {{ account_manager }} at hello@blueshift.io

{% include "legal-footer.md" %}
