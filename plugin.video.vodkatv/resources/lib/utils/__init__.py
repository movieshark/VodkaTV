from datetime import datetime


def unix_to_date(unix_time: int) -> str:
    """
    Convert a UNIX timestamp to a date string. This method is
     used to tranlate times returned by the Yeti API to
     human-readable strings.

    :param unix_time: The UNIX timestamp.
    :return: The date string.
    """
    return datetime.fromtimestamp(unix_time).strftime("%Y-%m-%d %H:%M:%S")
