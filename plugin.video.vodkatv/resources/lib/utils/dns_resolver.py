from random import choice

from requests import get


def resolve_domain(dns_host: str, domain: str) -> str:
    """
    Resolve the domain to an IP address using the given DNS host.

    :param domain: The domain.
    :return: The IP address.
    """
    # inspiration from: https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/
    params = {
        "name": domain,
        "type": "A",
    }
    response = get(
        dns_host,
        headers={"accept": "application/dns-json"},
        params=params,
    )
    response.raise_for_status()
    json_response = response.json()
    # check if the response is valid
    if json_response["Status"] != 0:
        raise Exception("Error resolving domain")
    # check if the response contains an answer
    if not json_response.get("Answer", []):
        raise Exception("No answer found")
    return json_response["Answer"][0]["data"]


def get_vtv_ip_from_mapi(user_agent: str) -> str:
    """
    Get the IP address of the VodkaTV server from the MovieShark API.

    :return: The IP address.
    """
    response = get(
        "https://mapi.mvshrk.xyz/api/v1/vtv/ips", headers={"User-Agent": user_agent}
    )
    response.raise_for_status()
    json_response = response.json()
    if not json_response:
        raise Exception("No answer found")
    return choice(json_response)["ip"]
