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
    ]

    additional_metadata = [
        ("Seller Won't Repair - Credit Alternative", "negotiation", "seller_wont_repair"),
        ("Buyer Cold Feet - Decision Framework", "problem", "buyer_cold_feet"),
        ("Lender Delay - Rate Lock Extension", "problem", "lender_delay"),
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
