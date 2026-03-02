"""
Default communication scenario seed data.
"""

from __future__ import annotations

from typing import Any


def default_communication_scenarios() -> list[dict[str, Any]]:
    """Return the default set of 50 scenario definitions."""
    scenarios: list[dict[str, Any]] = [
        {
            "scenario_name": "Appraisal Gap - Split Difference",
            "category": "negotiation",
            "trigger_conditions": {
                "situation_type": "appraisal_gap",
                "trigger": "appraisal_value < contract_price",
                "difference": ">= 5000",
            },
            "scripts": [
                {
                    "approach": "Split the Difference",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, the appraisal came in at {{APPRAISAL_VALUE}}, which is {{GAP_AMOUNT}} "
                        "below our contract price of {{CONTRACT_PRICE}}. A common solution is to meet in the middle: "
                        "you increase your down payment by {{HALF_GAP}}, and we ask the seller to reduce the price by "
                        "{{HALF_GAP}}. This keeps everyone's numbers reasonable. Would this work for you?"
                    ),
                    "seller_message": (
                        "Hi {{SELLER_NAME}}, the appraisal came in at {{APPRAISAL_VALUE}}, {{GAP_AMOUNT}} below contract. "
                        "The buyer is willing to increase their down payment by {{HALF_GAP}} if you would reduce your "
                        "price by {{HALF_GAP}}. This keeps the deal together. What are your thoughts?"
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, appraisal came in {{GAP_AMOUNT}} low at {{APPRAISAL_VALUE}}. Suggesting split: "
                        "buyer adds {{HALF_GAP}} cash, seller reduces {{HALF_GAP}}. This is a fair compromise that usually "
                        "works. Can you present to your client?"
                    ),
                },
                {
                    "approach": "Full Seller Concession",
                    "seller_message": (
                        "Hi {{SELLER_NAME}}, appraisal came in at {{APPRAISAL_VALUE}}, which is what the buyer's lender "
                        "will finance. To keep the deal moving forward, would you consider reducing the price to the "
                        "appraised value? The alternative is the buyer walks or we risk the deal falling through."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, appraisal at {{APPRAISAL_VALUE}}. We need seller to come down to appraised "
                        "value to keep buyer's financing intact. Can you present this to your seller?"
                    ),
                },
                {
                    "approach": "Buyer Covers Gap",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, appraisal came in {{GAP_AMOUNT}} low. To proceed, you would need to bring an "
                        "additional {{GAP_AMOUNT}} in cash at closing (total down payment becomes {{NEW_DOWN_PAYMENT}}). "
                        "Let me know if this works or if you'd like me to request a seller price reduction."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, appraisal {{GAP_AMOUNT}} low. Checking if buyer can cover gap with additional "
                        "cash. Will update shortly."
                    ),
                },
            ],
            "usage_count": 0,
            "success_rate": 0.75,
        },
        {
            "scenario_name": "Excessive Inspection Items",
            "category": "negotiation",
            "trigger_conditions": {
                "situation_type": "inspection_negotiate",
                "trigger": "inspection_items_count > 15",
            },
            "scripts": [
                {
                    "approach": "Prioritize Safety & Major",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, I reviewed your inspection report. There are {{INSPECTION_COUNT}} items, "
                        "which is common for this home. I recommend focusing on major safety items rather than cosmetic "
                        "issues. Let's discuss which repairs are most important to you."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, inspection found {{INSPECTION_COUNT}} items. I'm helping buyer prioritize top "
                        "3-5 safety/major items for repair request. This approach typically gets better seller response "
                        "than requesting all items."
                    ),
                },
                {
                    "approach": "Request All Plus Credit",
                    "seller_message": (
                        "Hi {{SELLER_NAME}}, buyer's inspection found {{INSPECTION_COUNT}} items totaling approximately "
                        "{{ESTIMATED_REPAIR_COST}}. Buyer is requesting repairs OR a credit of {{CREDIT_AMOUNT}} at closing "
                        "to handle repairs themselves. Please review and let me know your thoughts."
                    )
                },
            ],
            "usage_count": 0,
            "success_rate": 0.68,
        },
        {
            "scenario_name": "Seller Won't Repair",
            "category": "negotiation",
            "trigger_conditions": {
                "situation_type": "seller_wont_repair",
                "trigger": "manual_or_ai_detection",
            },
            "scripts": [
                {
                    "approach": "Credit at Closing Instead of Repairs",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, seller is hesitant to complete repairs directly. A common path is requesting "
                        "a closing credit so you can control the work after closing. We can propose a credit around "
                        "{{CREDIT_AMOUNT}} and keep timing on track for {{CLOSING_DATE}}."
                    ),
                    "seller_message": (
                        "Hi {{SELLER_NAME}}, to keep this transaction moving, would you consider a closing credit instead "
                        "of coordinating repairs? This often reduces your logistics and gives buyer flexibility after closing."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, seller repair resistance detected. Suggest offering a credit-in-lieu approach "
                        "to preserve timeline and reduce negotiation friction."
                    ),
                },
                {
                    "approach": "Safety Items Only",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, if seller won't address everything, we can narrow requests to safety/major "
                        "items only. That focused ask often gets approved and still protects your risk."
                    ),
                    "seller_message": (
                        "Hi {{SELLER_NAME}}, buyer is willing to narrow the request to top safety items so we can avoid a "
                        "larger amendment and stay on schedule."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, recommending a safety-items-only repair scope to improve odds of agreement."
                    ),
                },
                {
                    "approach": "Price Adjustment + Fast Close",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, another option is a purchase-price adjustment instead of repair coordination. "
                        "This simplifies execution and helps us maintain closing momentum."
                    ),
                    "seller_message": (
                        "Hi {{SELLER_NAME}}, buyer may accept a price adjustment in exchange for no repair coordination, "
                        "which can keep us on a clean path to {{CLOSING_DATE}}."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, proposing price-adjustment-for-speed as a third path when repair negotiations stall."
                    ),
                },
            ],
            "usage_count": 0,
            "success_rate": 0.67,
        },
        {
            "scenario_name": "Buyer Cold Feet",
            "category": "problem",
            "trigger_conditions": {
                "situation_type": "buyer_cold_feet",
                "trigger": "manual_or_ai_detection",
            },
            "scripts": [
                {
                    "approach": "Decision Framework + Facts",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, I hear your concerns and that's completely normal before closing. Let's walk "
                        "through your top 3 concerns and separate emotional stress from contract facts so you can make a "
                        "confident decision."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, buyer hesitation detected. Recommending a calm decision framework call today "
                        "to address concerns and stabilize the transaction."
                    ),
                },
                {
                    "approach": "24-Hour Pause + Reconfirm Plan",
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, let's take a 24-hour pause to review numbers, timelines, and your must-haves. "
                        "We'll reconnect tomorrow with a clear yes/no plan and next steps."
                    ),
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, proposing a short structured pause with follow-up tomorrow to reduce panic-driven decisions."
                    ),
                },
            ],
            "usage_count": 0,
            "success_rate": 0.64,
        },
        {
            "scenario_name": "Lender Delays",
            "category": "problem",
            "trigger_conditions": {
                "situation_type": "lender_delay",
                "trigger": "manual_or_ai_detection",
            },
            "scripts": [
                {
                    "approach": "Escalate with Document Checklist",
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, lender timeline is slipping. I’m sending a same-day checklist request so we can "
                        "clear conditions quickly and protect {{CLOSING_DATE}}."
                    ),
                    "lender_message": (
                        "Hi {{LENDER_NAME}}, can you share remaining conditions and priority order today so we can coordinate "
                        "documents immediately and keep closing on track?"
                    ),
                },
                {
                    "approach": "Extension Buffer + Rate Lock Protection",
                    "agent_message": (
                        "Hi {{AGENT_NAME}}, if lender confirms a delay, we should prep a short extension now to avoid last-minute "
                        "risk and protect the client’s rate lock position."
                    ),
                    "buyer_message": (
                        "Hi {{BUYER_NAME}}, lender processing may require a short extension. We’re proactively managing this "
                        "to keep costs and stress as low as possible."
                    ),
                },
            ],
            "usage_count": 0,
            "success_rate": 0.66,
        },
    ]

    additional_metadata = [
        ("Title Issue - Curative Timeline", "problem", "title_issue"),
        ("Extension Request - Cooperative Ask", "coordination", "extension_request"),
        ("Termination Notice - Professional Closeout", "update", "termination"),
        ("Rush Closing - Priority Checklist", "coordination", "rush_closing"),
        ("Financing Re-Underwrite Surprise", "problem", "financing_reunderwrite"),
        ("HOA Document Delay", "problem", "hoa_delay"),
        ("Survey Objection Negotiation", "negotiation", "survey_objection"),
        ("Insurance Binder Missing", "problem", "insurance_missing"),
        ("Earnest Money Delay", "coordination", "earnest_delay"),
        ("Option Fee Delay", "coordination", "option_fee_delay"),
        ("Appraisal Reconsideration Request", "negotiation", "appraisal_reconsideration"),
        ("Multiple Offer Backup Position", "negotiation", "backup_offer"),
        ("Buyer Job Change Alert", "problem", "buyer_job_change"),
        ("Seller Needs Leaseback", "negotiation", "leaseback_request"),
        ("Utility Transfer Confusion", "coordination", "utility_transfer"),
        ("Walkthrough Damage Discovered", "problem", "walkthrough_damage"),
        ("Closing Disclosure Discrepancy", "problem", "cd_discrepancy"),
        ("Wire Fraud Safety Reminder", "update", "wire_safety"),
        ("Seller Moving Delay", "problem", "seller_moving_delay"),
        ("Buyer Closing Cost Credit Request", "negotiation", "buyer_credit_request"),
        ("Lender Conditions Not Cleared", "problem", "lender_conditions"),
        ("Final Utility Readings Missing", "coordination", "utility_readings"),
        ("Home Warranty Disagreement", "negotiation", "home_warranty"),
        ("Pest Report Follow-up", "problem", "pest_report"),
        ("Foundation Concern After Inspection", "problem", "foundation_concern"),
        ("Roof Age Concern", "problem", "roof_concern"),
        ("Septic / Well Concern", "problem", "septic_well"),
        ("New Build Punch List Delay", "coordination", "new_build_punch_list"),
        ("Condo HOA Litigation Concern", "problem", "condo_litigation"),
        ("Title Endorsement Delay", "problem", "title_endorsement_delay"),
        ("Flood Insurance Requirement", "coordination", "flood_insurance"),
        ("Property Tax Proration Dispute", "negotiation", "tax_proration"),
        ("Escrow Shortage at Closing", "problem", "escrow_shortage"),
        ("Buyer Wants Early Possession", "negotiation", "early_possession"),
        ("Seller Wants Late Possession", "negotiation", "late_possession"),
        ("Occupancy Agreement Needed", "coordination", "occupancy_agreement"),
        ("Repairs Incomplete Before Closing", "problem", "repairs_incomplete"),
        ("Appliance / Fixture Inclusion Dispute", "negotiation", "fixture_dispute"),
        ("Personal Property Exclusion Dispute", "negotiation", "personal_property_dispute"),
        ("Loan Program Change Mid-File", "problem", "loan_program_change"),
        ("Appraisal Transfer Between Lenders", "coordination", "appraisal_transfer"),
        ("Co-borrower Added Late", "coordination", "coborrower_added"),
        ("Closing Location Change", "coordination", "closing_location_change"),
        ("Mobile Notary Coordination", "coordination", "mobile_notary"),
        ("Last-Minute Signature Missing", "problem", "signature_missing"),
    ]

    for scenario_name, category, situation_type in additional_metadata:
        scenarios.append(
            {
                "scenario_name": scenario_name,
                "category": category,
                "trigger_conditions": {
                    "situation_type": situation_type,
                    "trigger": "manual_or_ai_detection",
                },
                "scripts": [
                    {
                        "approach": "Collaborative Resolution",
                        "buyer_message": (
                            "Hi {{BUYER_NAME}}, quick update on {{PROPERTY_ADDRESS}} regarding "
                            f"{scenario_name.lower()}. My recommendation is a collaborative path that keeps us on track "
                            "for {{CLOSING_DATE}}. I can walk you through options and next steps today."
                        ),
                        "seller_message": (
                            "Hi {{SELLER_NAME}}, quick update on {{PROPERTY_ADDRESS}} regarding "
                            f"{scenario_name.lower()}. I'd like to propose a practical solution that protects timeline "
                            "and keeps the transaction moving. Can we review options together?"
                        ),
                        "agent_message": (
                            "Hi {{AGENT_NAME}}, scenario detected: "
                            f"{scenario_name}. Recommend collaborative framing with clear options and a same-day "
                            "decision window to preserve momentum."
                        ),
                    },
                    {
                        "approach": "Firm Timeline + Decision Deadline",
                        "buyer_message": (
                            "Hi {{BUYER_NAME}}, to keep {{PROPERTY_ADDRESS}} on schedule for {{CLOSING_DATE}}, we need a "
                            f"decision on {scenario_name.lower()} today. Please confirm your preferred option by end of day."
                        ),
                        "seller_message": (
                            "Hi {{SELLER_NAME}}, for {{PROPERTY_ADDRESS}}, we need to finalize "
                            f"{scenario_name.lower()} today to avoid downstream delays. Please confirm your direction by EOD."
                        ),
                        "agent_message": (
                            "Hi {{AGENT_NAME}}, we're setting a firm decision deadline on "
                            f"{scenario_name.lower()} to protect closing timeline at {{PROPERTY_ADDRESS}}."
                        ),
                    },
                ],
                "usage_count": 0,
                "success_rate": 0.62,
            }
        )

    # Guarantee exactly 50 scenarios.
    return scenarios[:50]
