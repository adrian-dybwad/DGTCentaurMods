# Assistants Module
#
# This file is part of the Universal-Chess project
# ( https://github.com/adrian-dybwad/Universal-Chess )
#
# Assistants are entities that help the user play. They provide suggestions,
# hints, or guidance without making moves themselves. Examples: Hand+Brain
# mode (suggests piece type), coach (evaluates positions), hint provider.
#
# Licensed under the GNU General Public License v3.0 or later.
# See LICENSE.md for details.

from .base import Assistant, AssistantConfig, Suggestion, SuggestionType
from .hand_brain import HandBrainAssistant, HandBrainConfig, create_hand_brain_assistant
from .hint import HintAssistant, HintConfig, create_hint_assistant

__all__ = [
    # Base classes
    'Assistant',
    'AssistantConfig',
    'Suggestion',
    'SuggestionType',
    # Hand+Brain assistant
    'HandBrainAssistant',
    'HandBrainConfig',
    'create_hand_brain_assistant',
    # Hint assistant
    'HintAssistant',
    'HintConfig',
    'create_hint_assistant',
]
