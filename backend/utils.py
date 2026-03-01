import re

def decompose_url(url: str) -> list[str]:
    """
    Decomposes a URL into alphanumeric components for embedding.
    Additionally, it removes common URL-specific tokens and overly long strings.
    """
    url = url.replace("http://", "").replace("https://", "").replace("www.", "")
    components = re.split(r'\W', url)

    # Filter out strings that contain alternating letters and numbers 
    # and strings that are too long
    pattern = r'(?:\d+[a-zA-Z]+\d+|[a-zA-Z]+\d+[a-zA-Z]+)'
    components = [comp for comp in components 
                  if comp
                  and not re.search(pattern, comp)
                  and len(comp) <= 20]
    return components
