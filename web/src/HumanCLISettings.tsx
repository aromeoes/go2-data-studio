import { useEffect, useState } from "react";

export type AgentModel = {
  provider: string;
  model: string;
  base_url: string;
  configured: boolean;
  vision: boolean;
  error?: string | null;
  environment_managed?: boolean;
};
export function HumanCLISettings({
  config,
  save,
  pending,
}: {
  config?: AgentModel;
  save: (value: {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
    vision: boolean;
  }) => Promise<void>;
  pending: boolean;
}) {
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4.1-mini");
  const [baseUrl, setBaseUrl] = useState("");
  const [vision, setVision] = useState(false);
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!config) return;
    setProvider(config.provider);
    setModel(config.model);
    setBaseUrl(config.base_url);
    setVision(config.vision);
  }, [config?.provider, config?.model, config?.base_url, config?.vision]);
  return (
    <details className="vision-settings">
      <summary>
        Agent model ·{" "}
        {config?.configured
          ? `${config.provider} / ${config.model}`
          : "Setup required"}
      </summary>
      <p>
        Uses the DimOS MCP agent. Your conversation and requested tool results
        go to the selected model. Credentials stay on this computer.
      </p>
      {config?.environment_managed && (
        <p>
          Environment settings override saved settings. Change .env and restart
          the application to change those overrides.
        </p>
      )}
      {config?.error && (
        <p role="alert" className="error-text">
          {config.error}
        </p>
      )}
      <form
        className="agent-model-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          try {
            await save({
              provider,
              model,
              api_key: key,
              base_url: baseUrl,
              vision,
            });
            setKey("");
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        <label>
          Provider
          <select
            aria-label="HumanCLI provider"
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setKey("");
              setBaseUrl("");
              setVision(false);
              setModel(e.target.value === "openai" ? "gpt-4.1-mini" : "");
            }}
          >
            <option value="openai">OpenAI / compatible</option>
            <option value="anthropic">Anthropic</option>
            <option value="google_genai">Google Gemini</option>
            <option value="ollama">Ollama (local)</option>
          </select>
        </label>
        <label>
          Model
          <input
            aria-label="HumanCLI model"
            required
            value={model}
            maxLength={160}
            placeholder="Tool-capable model ID"
            onChange={(e) => setModel(e.target.value)}
          />
        </label>
        {(provider === "openai" || provider === "ollama") && (
          <label>
            Endpoint (optional)
            <input
              aria-label="HumanCLI endpoint"
              type="url"
              value={baseUrl}
              placeholder={
                provider === "ollama"
                  ? "http://127.0.0.1:11434"
                  : "Default provider endpoint"
              }
              onChange={(e) => {
                setBaseUrl(e.target.value);
                setKey("");
                setVision(false);
              }}
            />
          </label>
        )}
        {provider !== "ollama" && (
          <label>
            API key
            <input
              aria-label="HumanCLI API key"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Leave blank to keep existing key"
            />
          </label>
        )}
        <label className="agent-vision-consent">
          <input
            type="checkbox"
            checked={vision}
            onChange={(e) => setVision(e.target.checked)}
          />{" "}
          Allow requested camera images to be sent to this model. Requires a
          vision-capable model.
        </label>
        {error && (
          <p role="alert" className="error-text">
            {error}
          </p>
        )}
        <button disabled={pending || !model.trim()}>Save agent settings</button>
      </form>
    </details>
  );
}
