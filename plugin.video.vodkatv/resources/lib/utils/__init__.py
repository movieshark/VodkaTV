from datetime import datetime, timezone
from time import mktime, strptime
from typing import Tuple


def unix_to_date(unix_time: int) -> str:
    """
    Convert a UNIX timestamp to a date string. This method is
     used to tranlate times returned by the Voda API to
     human-readable strings.

    :param unix_time: The UNIX timestamp.
    :return: The date string.
    """
    return datetime.fromtimestamp(unix_time).strftime("%Y-%m-%d %H:%M:%S")


def voda_to_epg_time(voda_time: str) -> Tuple[str, int]:
    """
    Convert Voda time to EPG time format and unix timestamp.

    :param voda_time: Voda time format
    :return: EPG time format (strftime("%Y%m%d%H%M%S %z")), unix timestamp
    """
    # ie. 14/08/2023 21:45:00 -> 20230809144500 +0200
    try:
        voda_time = datetime.strptime(voda_time, "%d/%m/%Y %H:%M:%S")
        return voda_time.strftime("%Y%m%d%H%M%S %z"), int(
            voda_time.replace(tzinfo=timezone.utc).timestamp()
        )
    # https://bugs.python.org/issue27400
    except TypeError:
        voda_time = datetime.fromtimestamp(
            mktime(strptime(voda_time, "%d/%m/%Y %H:%M:%S"))
        )
        return voda_time.strftime("%Y%m%d%H%M%S %z"), int(
            voda_time.replace(tzinfo=timezone.utc).timestamp()
        )
