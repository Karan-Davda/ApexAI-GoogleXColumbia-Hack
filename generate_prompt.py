import json
from pathlib import Path


def build_prompt(config: dict) -> str:
    agent = config["agent"]
    product_name = agent["company"]

    lines = []
    lines.append(f"You are {agent['name']}, {agent['title']} at {product_name}.")
    lines.append(
        f"{product_name} is a {agent['domain']} platform focused on automating manual comp analysis and reporting."
    )
    lines.append(f"Personality: {agent['personality']}")
    lines.append("")
    lines.append("VOICE RULES")
    lines.append("Always use contractions in natural spoken language.")
    lines.append("Use short conversational sentences.")
    lines.append("Avoid list style speech.")
    lines.append("React to what the customer said before your next point.")
    lines.append("")
    lines.append("PRODUCT KNOWLEDGE")
    for plan in config["plans"]:
        features = ", ".join(plan["features"][:3])
        lines.append(
            f"{plan['name']} costs ${plan['price_monthly']} monthly, supports {plan['user_limit']} users, and includes {features}."
        )
    lines.append("")
    lines.append("CRE CONTEXT")
    lines.append("CoStar is complementary and not a competitor.")
    lines.append("If customer mentions CoStar, position as productivity layer on top of existing CoStar workflow.")
    lines.append("")
    lines.append("STAGE CONTROL")
    lines.append("Track stages as GREETING then DISCOVERY then PITCH then OBJECTION_HANDLING then CLOSING.")
    lines.append("Update profile data as soon as details are learned.")
    lines.append("")
    lines.append("TOOL USE")
    lines.append("Call calculate_price for exact pricing questions.")
    lines.append("Call compare_competitor whenever a competitor is named.")
    lines.append("Call generate_recommendation for close intent or recommendation requests.")

    prompt = "\n".join(lines).replace("*", "").replace("#", "").replace("-", " ")
    return prompt


def generate_prompt() -> Path:
    config_path = Path("config.json")
    output_path = Path("prompts/system_prompt.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    prompt = build_prompt(config)
    output_path.write_text(prompt, encoding="utf-8")
    print(f"Wrote prompt to {output_path}")
    return output_path


if __name__ == "__main__":
    generate_prompt()
