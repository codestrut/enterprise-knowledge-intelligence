"""Test claim parsing and citation association."""

from src.generation.claim_parser import parse_claims


answer = (
    "An Organizational Profile is a CSF-based description of an "
    "organization’s current and/or target cybersecurity posture, "
    "framed in terms of the CSF Core outcomes. "
    "It can include a Current Profile (what is being achieved now) "
    "and/or a Target Profile (the desired outcomes), and may be "
    "used to tailor, assess, prioritize, and communicate cybersecurity "
    "risk management to stakeholders. "
    "[Source 1][Source 5]"
)


claims = parse_claims(answer)


print("\n" + "=" * 80)
print("PARSED CLAIMS")
print("=" * 80)


for index, claim in enumerate(claims, start=1):

    print(f"\nClaim {index}:")
    print(claim["claim"])

    print("Sources:")
    print(claim["source_numbers"])