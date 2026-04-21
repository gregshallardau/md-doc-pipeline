---
title: Employee Onboarding Form
author: Acme Corp
date: April 2026
outputs: [pdf]
pdf_forms: true
cover_page: false
---

# Employee Onboarding Form

Please complete all sections below. Required fields are marked with an asterisk (*).

<form markdown="1">

---

## Personal Details

<strong>Full name</strong> *
<input type="text" name="full_name" required maxlength="100">

<strong>Preferred name</strong> (if different)
<input type="text" name="preferred_name" maxlength="50">

<strong>Date of birth</strong> *
<input type="date" name="date_of_birth" required>

<strong>Email address</strong> *
<input type="email" name="email" required>

<strong>Phone number</strong> *
<input type="text" name="phone" required maxlength="20">

<strong>Home address</strong> *
<textarea name="home_address" rows="3"></textarea>

---

## Employment Details

<strong>Position title</strong> *
<input type="text" name="position_title" required>

<strong>Department</strong> *
<select name="department">
  <option value="">— Select department —</option>
  <option value="engineering">Engineering</option>
  <option value="sales">Sales</option>
  <option value="marketing">Marketing</option>
  <option value="finance">Finance</option>
  <option value="operations">Operations</option>
  <option value="hr">Human Resources</option>
  <option value="other">Other</option>
</select>

<strong>Start date</strong> *
<input type="date" name="start_date" required>

<strong>Employment type</strong> *

<div>
<label style="display: inline; margin-right: 12pt;"><input type="radio" name="employment_type" value="fulltime"> Full-time</label>
<label style="display: inline; margin-right: 12pt;"><input type="radio" name="employment_type" value="parttime"> Part-time</label>
<label style="display: inline; margin-right: 12pt;"><input type="radio" name="employment_type" value="contract"> Contract</label>
<label style="display: inline;"><input type="radio" name="employment_type" value="casual"> Casual</label>
</div>

---

## Emergency Contact

<strong>Contact name</strong> *
<input type="text" name="emergency_name" required>

<strong>Relationship</strong>
<input type="text" name="emergency_relationship">

<strong>Contact phone</strong> *
<input type="text" name="emergency_phone" required>

---

## Bank Details (for payroll)

Three fields side by side using a table layout:

<table style="border: none; width: 100%;">
<tr style="background: none;">
<td style="border: none; width: 33%; padding: 0 8pt 0 0; vertical-align: top;">
<strong>Account name</strong> *<br>
<input type="text" name="bank_account_name" required>
</td>
<td style="border: none; width: 33%; padding: 0 8pt; vertical-align: top;">
<strong>BSB</strong> *<br>
<input type="text" name="bank_bsb" required maxlength="7">
</td>
<td style="border: none; width: 33%; padding: 0 0 0 8pt; vertical-align: top;">
<strong>Account number</strong> *<br>
<input type="text" name="bank_account_number" required maxlength="12">
</td>
</tr>
</table>

---

## IT Setup

<strong>Preferred laptop</strong> *
<select name="laptop_preference">
  <option value="">— Select —</option>
  <option value="macbook_pro_14">MacBook Pro 14"</option>
  <option value="macbook_pro_16">MacBook Pro 16"</option>
  <option value="dell_xps_15">Dell XPS 15</option>
  <option value="thinkpad_x1">ThinkPad X1 Carbon</option>
</select>

<strong>Additional monitors needed</strong>
<input type="number" name="monitors" min="0" max="3">

<strong>Software requirements</strong> (list any specific tools you need)
<textarea name="software_requirements" rows="3"></textarea>

---

## Agreements

<div>
<label><input type="checkbox" name="policy_ack" required> I have read and agree to the Employee Code of Conduct *</label><br>
<label><input type="checkbox" name="privacy_ack" required> I consent to the collection and processing of my personal information as described in the Privacy Policy *</label><br>
<label><input type="checkbox" name="it_ack" required> I have read and agree to the IT Acceptable Use Policy *</label>
</div>

---

<strong>Signature</strong>
<input type="text" name="signature" required>

<strong>Date</strong>
<input type="date" name="signature_date" required>

<input type="submit" value="Submit Form">

</form>
