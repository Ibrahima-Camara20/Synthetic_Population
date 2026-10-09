import time
import ollama

MODEL = "llama3" #Write the chosen model

agent_a = {
    "name": "Benjamin",
    "role": "Une personne jeune, insouciante et riche.",
}

agent_b = {
    "name": "Catherine",
    "role": "Une personne agée et consciencieuse avec une petite retraite.",
}


def get_response(agent, conversation_log):
    """Generates a response from an agent based on the full dialogue so far."""
    system_prompt = (
        f"Vous êtes {agent['name']}. {agent['role']}\n"
        "Répondez directement à la personne précedente."
        "Essayez de ne pas vous répétez."
        "Limitez vous à 2-3 phrases."
        "En francais et en argumentant."
    )

    # Format entire dialogue history as user context for the agent
    prompt_content = "Voici la conversation:\n"
    for speaker, text in conversation_log:
        prompt_content += f"{speaker}: {text}\n"

    prompt_content += f"\nRepondez comme {agent['name']}."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt_content},
    ]

    response = ollama.chat(model=MODEL, messages=messages)
    return response["message"]["content"]


def run_conversation(topic, turns=4):
    print(f"=== Conversation: '{topic}' ===\n")

    # Simple list of (speaker_name, text) tuples
    conversation_log = [("Topic", f"Qu'est-ce que vous pensez du'{topic}'?")]

    for i in range(turns):
        # --- Agent A's Turn ---
        res_a = get_response(agent_a, conversation_log)
        print(f"\033[94m{agent_a['name']}\033[0m: {res_a}\n")
        conversation_log.append((agent_a["name"], res_a))

        time.sleep(1)

        # --- Agent B's Turn ---
        res_b = get_response(agent_b, conversation_log)
        print(f"\033[93m{agent_b['name']}\033[0m: {res_b}\n")
        conversation_log.append((agent_b["name"], res_b))

        time.sleep(1)


if __name__ == "__main__":
    run_conversation(topic="Montant des cotisations retraites? Faut il assurer des retraites convenables? Ou est-il à chacun d'assurer la leur?", turns=6)