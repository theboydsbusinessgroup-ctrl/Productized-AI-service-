import re
from typing import Any


def _clean(value: str | None, fallback: str) -> str:
    value=(value or '').strip()
    return value or fallback


def build_content_pack(intake: dict[str, Any], order_id: str) -> str:
    business=_clean(intake.get('business_name'),'Your Business')
    industry=_clean(intake.get('industry'),'business')
    target=_clean(intake.get('target_customer'),'your ideal customers')
    tone=_clean(intake.get('tone'),'professional and approachable')
    location=_clean(intake.get('location'),'your service area')
    services=[str(x).strip() for x in intake.get('services',[]) if str(x).strip()]
    promotions=[str(x).strip() for x in intake.get('promotions',[]) if str(x).strip()]
    platforms=[str(x).strip() for x in intake.get('platforms',[]) if str(x).strip()] or ['Instagram','Facebook']
    instructions=_clean(intake.get('instructions'), 'No additional instructions supplied.')
    service=services[0] if services else f'{industry} services'
    service_list=', '.join(services) if services else service
    promo=promotions[0] if promotions else 'your current offer or preferred call to action'

    hooks=[
        f'Looking for {service} in {location}? Start with these three questions.',
        f'The biggest mistake people make when choosing a {industry} provider.',
        f'Before you spend money on {service}, know this.',
        f'What should {target} expect from a great {industry} experience?',
        f'3 signs you are choosing the right team for {service}.',
        f'One simple way to get better results from {service}.',
        f'What we wish more customers knew before booking {service}.',
        f'Price matters, but these factors matter just as much when choosing {service}.',
        f'If {service} feels overwhelming, use this simple checklist.',
        f'Here is what a smooth {industry} process should actually feel like.',
    ]

    posts=[
        f'EDUCATION — {business}: A strong {service} decision starts with clarity. Before hiring anyone, define the result you want, your timeline, and the questions that matter most. We help {target} move forward with a clear plan and fewer surprises.',
        f'PROBLEM / SOLUTION — Too many {target} wait until a small issue becomes an expensive one. If you need {service} in {location}, address the problem early, compare realistic options, and choose the solution that fits the actual goal—not just the fastest answer.',
        f'PROCESS — Wondering what happens after you contact {business}? Start with your goal, review the situation, choose the right next step, and keep communication clear through completion. A good {industry} experience should feel organized from beginning to end.',
        f'FAQ — “How do I know which {service} option is right for me?” Start with scope, timing, priorities, and budget. The best choice is the one that solves the real problem without adding unnecessary complexity.',
        f'TRUST — Good service is not about making the biggest promise. It is about setting clear expectations, communicating well, and following through. That is the standard {business} should reinforce in every customer interaction.',
        f'LOCAL — If you are comparing {industry} options in {location}, look beyond the first listing you find. Ask about fit, availability, communication, and what is actually included before making a decision.',
        f'BEHIND THE SCENES — A smooth customer experience usually comes from the work people never see: preparation, checklists, communication, and quality control. Those details are what turn {service} from a transaction into a professional experience.',
        f'MYTH — You do not always need the most complicated solution. For many {target}, the right {service} plan is the one that solves the priority problem clearly, efficiently, and within realistic constraints.',
        f'DECISION POST — Comparing providers for {service}? Write down your top three priorities before you call anyone. It makes questions sharper, quotes easier to compare, and the final decision much easier.',
        f'CALL TO ACTION — Need help with {service} in {location}? Contact {business} with your goal, timing, and the biggest question you need answered. A clear first conversation can save a lot of unnecessary back-and-forth.',
    ]

    captions=[
        f'Clarity first. Better decisions follow. If you are planning {service}, start with the outcome you actually need. #{industry.replace(" ","")} #SmallBusiness',
        f'Not every {service} option is the right fit. Ask better questions before you commit.',
        f'A smoother {industry} experience starts long before the work begins: plan, communicate, confirm.',
        f'Choosing {service}? Compare scope and expectations—not just price.',
        f'The details customers do not see are often the details that make the experience feel effortless.',
        f'For {target}: define the goal, understand the options, then choose the simplest path that gets the result.',
        f'Local help matters. If you need {service} in {location}, work with a provider who communicates clearly about what happens next.',
        f'Good service should reduce uncertainty, not create more of it.',
        f'One useful question before booking {service}: “What exactly is included, and what happens after I say yes?”',
        f'Ready to move forward with {service}? Send {business} your goal and timeline to start the conversation.',
    ]

    promo_ideas=[
        f'Create a limited-time campaign around {promo}; state the real deadline and terms clearly.',
        f'Bundle a high-demand service with a useful add-on from this list: {service_list}. Price it only after confirming margin.',
        f'Offer a simple “start here” consultation or assessment that helps qualified prospects choose the right {service} option.',
        f'Run a referral campaign that rewards existing customers only if the economics remain profitable and the terms are disclosed.',
        f'Build a seasonal or event-based offer for {location} using a real customer need rather than an artificial discount.',
    ]

    gbp_posts=[
        f'{business} helps customers in {location} with {service}. If you are comparing options, start by sharing your goal and timeline so the right next step can be identified quickly.',
        f'Need {service}? Before choosing a provider, confirm scope, timing, what is included, and how communication will work. Contact {business} to discuss your needs.',
        f'A professional {industry} experience should be clear from the first conversation through completion. {business} focuses on organized communication and practical next steps for customers in {location}.',
        f'Planning ahead for {service} can prevent rushed decisions later. Reach out to {business} with your priorities and questions so you can evaluate the best path forward.',
        f'If you are looking for {service} in {location}, make your decision based on fit, clarity, and realistic expectations. Contact {business} to get started.',
    ]

    # Use every requested service and supported tone rather than one repeated service.
    lead = {'friendly': 'Let’s make this easier.', 'casual': 'Here’s a practical starting point.',
            'professional': 'A useful planning step:', 'playful': 'A little planning goes a long way.'}
    tone_lead = next((text for key,text in lead.items() if key in tone.lower()), 'Start with a clear plan.')
    for index in range(len(posts)):
        selected = services[index % len(services)] if services else service
        posts[index] = tone_lead + ' ' + posts[index].replace(service, selected)
        hooks[index] = hooks[index].replace(service, selected)
        captions[index] = captions[index].replace(service, selected)
    if promotions:
        promo_ideas = [f'Campaign {i+1}: feature the customer-supplied offer “{p}” for {business}. Verify its terms and availability before posting.' for i,p in enumerate(promotions)]
        while len(promo_ideas) < 5:
            promo_ideas.append(f'Campaign {len(promo_ideas)+1}: answer a common question about {services[len(promo_ideas)%len(services)] if services else service} and invite {target} to contact {business}.')
        promo_ideas = promo_ideas[:5]
    if re.search(r'\b(no|avoid|without|do not use|don.t use)\s+(hashtags?|hash tags?)', instructions, re.I):
        captions = [re.sub(r'\s*#\w+', '', text) for text in captions]
    if re.search(r'\b(no|avoid|without|do not offer|don.t offer)\s+(discounts?|promotions?)', instructions, re.I):
        promo_ideas = [f'Campaign {i+1}: explain what to ask about {services[i%len(services)] if services else service}; invite an inquiry without discounts, urgency, or price promises.' for i in range(5)]


    calendar_types=['Educational post','Hook + short caption','FAQ post','Google Business Profile post','Behind-the-scenes post','Offer / CTA','Trust-building post','Local post','Myth-busting post','Decision checklist']
    calendar=[]
    for day in range(1,31):
        kind=calendar_types[(day-1)%len(calendar_types)]
        platform=platforms[(day-1)%len(platforms)]
        reference = f'Social Post {(day-1)%10+1}' if day % 3 != 0 else f'GBP Post {(day-1)%5+1}'
        calendar.append(f'Day {day}: {kind} on {platform} — use {reference}; pair with Hook {(day-1)%10+1} and Caption {(day-1)%10+1}.')

    lines=[
        f'# 30-Day Social Content Pack — {business}',
        '',
        f'Order: {order_id}',
        f'Industry: {industry}',
        f'Target customer: {target}',
        f'Location: {location}',
        f'Tone requested: {tone}',
        f'Primary services: {service_list}',
        '',
        '## Your publishing brief',
        f'Website: {_clean(intake.get("website"), "Not supplied")}',
        f'Platforms: {", ".join(platforms)}',
        f'Additional instructions: {instructions}',
        'Generation method: structured draft templates using your intake. No website research or external fact verification was performed. Free-form instructions are retained in this brief for review; supported no-hashtag/no-discount constraints are applied automatically.',
        '',
        '> Publishing note: Review every post for current pricing, availability, claims, and local requirements before publishing. Replace any offer language with verified terms.',
        '',
        '## 10 Hooks',
    ]
    lines += [f'{i}. {x}' for i,x in enumerate(hooks,1)]
    lines += ['', '## 10 Social Posts'] + [f'### Post {i}\n{x}' for i,x in enumerate(posts,1)]
    lines += ['', '## 10 Captions'] + [f'{i}. {x}' for i,x in enumerate(captions,1)]
    lines += ['', '## 5 Promotional Ideas'] + [f'{i}. {x}' for i,x in enumerate(promo_ideas,1)]
    lines += ['', '## 5 Google Business Profile Posts'] + [f'### GBP Post {i}\n{x}' for i,x in enumerate(gbp_posts,1)]
    lines += ['', '## 30-Day Content Calendar'] + calendar
    lines += ['', '## Recommended Workflow', '1. Pick the day’s content type.', '2. Match it to the closest post, hook, or caption above.', '3. Add a real photo, short video, customer-safe visual, or branded graphic.', '4. Verify all claims, pricing, dates, and availability.', '5. Publish and track replies, saves, clicks, and inquiries.', '']
    return '\n'.join(lines)
