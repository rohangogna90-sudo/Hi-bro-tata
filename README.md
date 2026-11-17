# Personal AI Assistant — starter project

A private, single-owner Android AI assistant starter. It includes:
- Expo / React Native mobile chat app
- FastAPI backend
- Owner-password login and signed access tokens
- Gemini, OpenAI Responses API, and Anthropic Messages API adapters
- Server-side API keys (never put provider keys in the APK)
- APK build profile for Expo's cloud build service

This is **Phase 1: a working text-chat foundation**. It does not yet include web search,
weather, YouTube search, Android app control, voice, or self-modifying code. Those are
planned as separate permission-controlled tools.

## Project layout

- `mobile/` — Android app source
- `backend/` — API server
- `render.yaml` — Render deployment blueprint

## 1. Deploy the backend

1. Create a private GitHub repository and upload this project.
2. In Render, create a **Web Service** from that repository.
3. Set the Root Directory to `backend`.
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variables in Render:

| Variable | Value |
|---|---|
| `OWNER_PASSWORD` | A long private password only you know |
| `JWT_SECRET` | A random secret of at least 32 characters |
| `AI_PROVIDER` | `gemini` |
| `GEMINI_API_KEY` | Your Gemini API key |
| `GEMINI_MODEL` | `gemini-3.8-flash` |

Optional providers:
- `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-6-astra`)
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-sonnet-5`)

Set `AI_PROVIDER` to `gemini`, `openai`, or `anthropic` to choose the active provider.
Provider model names can be changed in Render environment variables as providers update models.

**Do not send API keys or your owner password in chat or commit them to GitHub.**
The app sends chat requests to your backend; provider keys stay on the backend.

After deployment, test:
- `https://YOUR-RENDER-SERVICE.onrender.com/health`

It should return `{"ok":true,"service":"personal-ai-assistant-api"}`.

## 2. Configure the Android app

1. Open `mobile/`.
2. Copy `.env.example` to `.env`.
3. Set `EXPO_PUBLIC_API_URL` to your deployed backend URL, without a trailing slash.
4. Install dependencies in a terminal:
   `npm install`
5. Start the app:
   `npx expo start`

The first screen asks for the owner password you set as `OWNER_PASSWORD` on Render.
The app stores the returned access token using Expo SecureStore.

## 3. Build a directly installable APK

From the `mobile/` directory, run:

```bash
npx eas-cli login
npx eas-cli build --platform android --profile preview
```

Expo's cloud builder will produce an APK download link. Open that link on your Android
phone and install the APK. You may need to allow installation from your browser.

The `preview` profile in `eas.json` is configured for APK output.

## 4. Switch AI providers

Change `AI_PROVIDER` in the Render environment:
- `gemini`
- `openai`
- `anthropic`

Add the corresponding provider key to Render. Restart/redeploy the service after changing
environment variables. Do not put provider keys in `mobile/.env`.

## 5. Next development phases

1. Add provider selection inside the app.
2. Add tool calling: web search, weather, YouTube search, calculator, website/file creation.
3. Add voice recognition and speech output, starting with English and Hindi.
4. Add monitoring: structured logs, error reporting, health checks and alerts.
5. Add permission-based self-improvement:
   - inspect an error and propose a patch
   - create a backup / isolated branch
   - run tests in a sandbox
   - show a diff and explanation
   - require your explicit approval before applying/deploying
   - keep rollback available

The self-improvement engine is **not enabled in this starter**. It must never be allowed to
silently rewrite production code or deploy without your approval.

## Security notes

- Use HTTPS for the deployed backend.
- Keep the GitHub repository private while it contains private project details.
- Use a unique, long owner password and JWT secret.
- Rotate any key immediately if it is accidentally exposed.
- Add login rate limiting and stronger operational monitoring before exposing the backend
  beyond your own use.
- This is a starter, not a security audit or production certification.
