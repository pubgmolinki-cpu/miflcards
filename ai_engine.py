import random

def calculate_team_strength(rating, form):
    return (rating * 0.7) + (form * 0.3)


def calculate_match_odds(team1_rating, team2_rating, form1, form2):

    power1 = calculate_team_strength(team1_rating, form1)
    power2 = calculate_team_strength(team2_rating, form2)

    diff = power1 - power2

    if diff > 10:
        return {
            "home": 1.55,
            "draw": 4.2,
            "away": 5.7
        }

    if diff > 5:
        return {
            "home": 1.85,
            "draw": 3.6,
            "away": 4.1
        }

    if diff > 0:
        return {
            "home": 2.1,
            "draw": 3.3,
            "away": 3.1
        }

    return {
        "home": 3.4,
        "draw": 3.5,
        "away": 1.9
    }


def generate_ai_analysis(team1, team2, form1, form2):

    lines = []

    if form1 > form2:
        lines.append(f"{team1} имеют лучшую форму")
    else:
        lines.append(f"{team2} выглядят стабильнее")

    lines.append("ИИ ожидает открытый матч")

    return "\n".join(lines)


def simulate_match(team1, team2):

    g1 = random.randint(0, 4)
    g2 = random.randint(0, 4)

    return {
        "score": f"{g1}:{g2}",
        "winner": team1 if g1 > g2 else team2 if g2 > g1 else "DRAW"
      }
