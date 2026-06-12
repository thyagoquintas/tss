# Docker

Esta imagem foi preparada para Ubuntu ARM64 na porta `5005`.

## Subir direto no servidor

```bash
docker compose up -d --build
```

Acesse:

```text
http://SEU_SERVIDOR:5005
```

Ver logs:

```bash
docker compose logs -f
```

Parar:

```bash
docker compose down
```

## Build manual

```bash
docker build -t kokoro-tts:arm64 .
docker run -d --name kokoro-tts -p 5005:5005 --restart unless-stopped kokoro-tts:arm64
```

## Build e push para ARM64 usando buildx

```bash
docker buildx build --platform linux/arm64 -t SEU_USUARIO/kokoro-tts:arm64 --push .
```

No servidor:

```bash
docker run -d --name kokoro-tts -p 5005:5005 --restart unless-stopped SEU_USUARIO/kokoro-tts:arm64
```

## Observacoes

- O primeiro uso pode demorar porque o Kokoro baixa o modelo e as vozes do Hugging Face.
- Se quiser evitar limites anonimos do Hugging Face, passe `HF_TOKEN` no container.
- Esta configuracao usa CPU em ARM64. CUDA da maquina Windows nao entra no Docker do servidor ARM.
