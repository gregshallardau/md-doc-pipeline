---
title: General Liability Insurance Application
outputs: [pdf]
pdf_forms: true
output_filename: "Stormfront-Liability-Application"
cover_page: false
date: 1 April 2026
---

{% include "company-header.md" %}

# General Liability Insurance Application

**Application process:** complete all sections below, then email the
application to {{ support_email | default("hello@blueshift.io") }}.

## 1) Contact Details

?[box]
**Insured Name** *Including any individual and any registered business name* ?[text: insured_name, required]
**Contact Name** ?[text: contact_name, required]
**Address** ?[text: address]
**City** ?[text: city] | **State** ?[text: state] | **Post Code** ?[text: post_code]
**Phone** ?[tel: phone] | **Email** ?[email: email, title=Where your policy documents will be sent]
**ABN** ?[text: abn, maxlength=14]
?[/box]

## 2) Limit of Indemnity

?[box]
Please tick the liability sum insured required
?[checkbox: limit_10m, label=$10 000 000] | ?[checkbox: limit_20m, label=$20 000 000]
?[/box]

## 3) Turnover

?[box: widths=72,28]
Total turnover derived from your business activities over the last 12 months: | $ ?[number: turnover_last_12]
Estimated turnover over the next 12 months: | $ ?[number: turnover_next_12]
?[/box]

## 4) Business Split

| Activity | % of turnover | $ amount |
|:---------|:--------------|:---------|
| Consulting | ?[number: split_consulting_pct] | ?[number: split_consulting_amt] |
| Training | ?[number: split_training_pct] | ?[number: split_training_amt] |
| Facility hire | ?[number: split_facility_pct] | ?[number: split_facility_amt] |

## 5) Cover Questions

?[box: widths=72,28]
Do you require cover for activities at client premises? *If No, go to Section 6.* | ?[yesno: client_premises]
How many staff deliver services off-site? (on average) | ?[number: offsite_staff]
What is the largest single contract value in the last 12 months? | $ ?[number: largest_contract]
Do you subcontract any services? (If yes, provide details below) | ?[yesno: subcontracts]
?[textarea: subcontract_details, rows=3]
?[/box]

## Declaration

I declare the information provided in this application is true and correct.

?[row]
?[signature: applicant_signature] | **Date** ?[date: declaration_date]
?[/row]

{% include "legal-footer.md" %}
