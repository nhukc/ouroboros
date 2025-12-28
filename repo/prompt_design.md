# Principles of Prompt Design

These principles govern how AI players reason and make decisions in this game.

## Richness and Behavior
- A model's behavior is governed by the richness of its prompt.
- A prompt with narrow or no information will result in a model that acts in the strictest and least interesting sense.

## Choice and Tools
- Injecting data directly into a prompt removes the aspect of choice.
- Supplying tools and optional data sources allows selective behavior and therefore more variation in results.
- The mechanism of choice must be used carefully - if a model refuses an option the results may be catastrophic.

## Response Structure
- Requests for responses should always ask for selections from fixed options as the final statement. This allows the attention mechanism to perform properly.

## Variation
- Sources of randomness such as randomly selected strings can create variation between two instances acting on the same prompt.

## Attention and Memory
- Recent text has more influence over the next tokens but original text accumulates within the model's KV cache.
