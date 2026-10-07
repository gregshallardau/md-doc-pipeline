---
title: Every supported form control
pdf_forms: true
outputs: [pdf, docx, dotx]
---
# Every supported form control

## Text inputs and attributes

**Name** ?[text: name, required, maxlength=80, title=Full name]

**Email** ?[email: email, required]

**Telephone** ?[tel: phone]

**Website** ?[url: website]

**Date** ?[date: date]

**Number** ?[number: quantity, min=0, max=10, step=1, value=2]

**Read only** ?[text: reference, readonly, value=SAMPLE-001]

**Comments** ?[textarea: comments, rows=2]

## Choices

?[checkbox: agreement, required] Agree to the sample terms

?[select: department | Select one | Engineering | Operations]

?[radio: delivery | Email | Post]

?[radio-inline: urgency | Standard | Urgent]

?[checkbox-inline: channels | Email | Phone | Portal]

?[yesno: consent]

<!-- pagebreak -->

## Structured form layouts

?[row]
**City** ?[text: city] | **Post code** ?[text: postcode]
?[/row]

?[box: widths=70,30]
Question | Response
Do you require follow-up? | ?[yesno: followup]
Preferred time | ?[text: time]
?[/box]

?[signature: signature, required]

?[submit Send]

## Word template markers

Recipient [[contact_name]] at [[company]]. The companion DOTX contains native Word form fields. A separate merge variant uses MERGEFIELDs.
