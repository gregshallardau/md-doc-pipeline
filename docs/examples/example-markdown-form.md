---
title: Employee Onboarding Form (Markdown Syntax)
author: Acme Corp
date: April 2026
outputs: [pdf]
pdf_forms: true
cover_page: false
---

# Employee Onboarding Form

Please complete all sections below. Required fields are marked with an asterisk (*).

---

## Personal Details

**Full name** *
?[text: full_name, required, maxlength=100]

**Preferred name** (if different)
?[text: preferred_name, maxlength=50]

**Date of birth** *
?[date: date_of_birth, required]

**Email address** *
?[email: email, required]

**Phone number** *
?[text: phone, required, maxlength=20]

**Home address** *
?[textarea: home_address, rows=3]

---

## Employment Details

**Position title** *
?[text: position_title, required]

**Department** *
?[select: department | -- Select department -- | Engineering | Sales | Marketing | Finance | Operations | Human Resources | Other]

**Start date** *
?[date: start_date, required]

**Employment type** *
?[radio-inline: employment_type | Full-time | Part-time | Contract | Casual]

---

## Emergency Contact

?[row]
?[text: emergency_name, required] | ?[text: emergency_relationship] | ?[text: emergency_phone, required]
?[/row]

---

## Bank Details (for payroll)

?[row]
?[text: bank_account_name, required] | ?[text: bank_bsb, required, maxlength=7] | ?[text: bank_account_number, required, maxlength=12]
?[/row]

---

## IT Setup

**Preferred laptop** *
?[select: laptop_preference | -- Select -- | MacBook Pro 14 | MacBook Pro 16 | Dell XPS 15 | ThinkPad X1 Carbon]

**Additional monitors needed**
?[number: monitors, min=0, max=3]

**Software requirements** (list any specific tools you need)
?[textarea: software_requirements, rows=3]

---

## Skills

**Programming languages**
?[checkbox-inline: skill | Python | JavaScript | Go | Rust | Java | C++]

---

## Agreements

?[checkbox: policy_ack, required]  I have read and agree to the Employee Code of Conduct *

?[checkbox: privacy_ack, required]  I consent to the collection and processing of my personal information *

?[checkbox: it_ack, required]  I have read and agree to the IT Acceptable Use Policy *

---

?[signature: signature, required]

**Date**
?[date: signature_date, required]

?[submit: Submit Form]
