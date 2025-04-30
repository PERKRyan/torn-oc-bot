def suggest_oc(player_cpr, current_scope):
    """
    Given a player's CPR record and current faction scope,
    suggest the highest OC they qualify for.
    """

    # Extract average CPR across roles
    cpr_values = [
        player_cpr.get('CPR Leader', 0),
        player_cpr.get('CPR Hacker', 0),
        player_cpr.get('CPR Driver', 0),
        player_cpr.get('CPR Pointman', 0),
        player_cpr.get('CPR Other', 0)
    ]
    avg_cpr = sum(cpr_values) / len([c for c in cpr_values if c > 0])

    # OC Levels and requirements
    oc_levels = [
        {"level": 8, "min_cpr": 60, "scope_cost": 4},
        {"level": 7, "min_cpr": 65, "scope_cost": 4},
        {"level": 6, "min_cpr": 70, "scope_cost": 4},
        {"level": 5, "min_cpr": 70, "scope_cost": 2},
        {"level": 4, "min_cpr": 70, "scope_cost": 2},
        {"level": 3, "min_cpr": 70, "scope_cost": 2},
        {"level": 2, "min_cpr": 70, "scope_cost": 1},
        {"level": 1, "min_cpr": 0,  "scope_cost": 1}
    ]

    # Find the best matching OC
    for oc in oc_levels:
        if avg_cpr >= oc["min_cpr"] and current_scope >= oc["scope_cost"]:
            return oc["level"], oc["scope_cost"]

    return None, None
