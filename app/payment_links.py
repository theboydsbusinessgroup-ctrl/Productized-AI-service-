"""Validate hosted checkout destinations and bind one authoritative reference."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def build_payment_link(base: str, parameters: dict[str, str]) -> str:
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or parsed.hostname != 'buy.stripe.com'
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment
            or parsed.path in ('', '/') or any(c.isspace() for c in base)):
        raise ValueError('Invalid Stripe Payment Link URL')
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key not in parameters]
    query.extend(parameters.items())
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))
