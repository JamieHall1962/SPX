from datetime import datetime

def get_next_futures_month() -> str:
    """
    Get the next ES futures contract month in YYYYMM format.
    ES futures expire on the 3rd Friday of March(H), June(M), Sept(U), Dec(Z).
    """
    current_date = datetime.now()
    current_month = current_date.month
    current_year = current_date.year
    
    print(f"Current date: {current_date}")
    print(f"Current month: {current_month}")
    print(f"Current year: {current_year}")

    # Map to futures months (Mar, Jun, Sep, Dec)
    futures_months = {3: 'H', 6: 'M', 9: 'U', 12: 'Z'}
    
    # Find next futures month
    for month in [3, 6, 9, 12]:
        if current_month < month:
            next_month = month
            next_year = current_year
            print(f"Next futures: {next_year}{next_month:02d}")
            break
    else:  # If we're past December
        next_month = 3  # Next is March
        next_year = current_year + 1
        print(f"Next futures (year rollover): {next_year}{next_month:02d}")

    result = f"{next_year}{next_month:02d}"
    print(f"Returning: {result}")
    return result 