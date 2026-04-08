import aliyunCodingPlanIcon from "./provider-icons/aliyun-codingplan.png";
import anthropicIcon from "./provider-icons/anthropic.png";
import azureOpenAiIcon from "./provider-icons/azure-openai.png";
import copawLocalIcon from "./provider-icons/copaw-local.png";
import dashscopeIcon from "./provider-icons/dashscope.png";
import deepseekIcon from "./provider-icons/deepseek.png";
import defaultIcon from "./provider-icons/default.jpg";
import geminiIcon from "./provider-icons/gemini.png";
import kimiIcon from "./provider-icons/kimi.png";
import lmstudioIcon from "./provider-icons/lmstudio.png";
import minimaxIcon from "./provider-icons/minimax.png";
import modelscopeIcon from "./provider-icons/modelscope.png";
import ollamaIcon from "./provider-icons/ollama.png";
import openaiIcon from "./provider-icons/openai.png";
import zhipuIcon from "./provider-icons/zhipu.png";

export const PROVIDER_ICON_BY_ID: Record<string, string> = {
  modelscope: modelscopeIcon,
  "aliyun-codingplan": aliyunCodingPlanIcon,
  deepseek: deepseekIcon,
  gemini: geminiIcon,
  "azure-openai": azureOpenAiIcon,
  "kimi-cn": kimiIcon,
  "kimi-intl": kimiIcon,
  anthropic: anthropicIcon,
  ollama: ollamaIcon,
  "minimax-cn": minimaxIcon,
  minimax: minimaxIcon,
  openai: openaiIcon,
  dashscope: dashscopeIcon,
  lmstudio: lmstudioIcon,
  "copaw-local": copawLocalIcon,
  "zhipu-cn": zhipuIcon,
  "zhipu-intl": zhipuIcon,
  "zhipu-cn-codingplan": zhipuIcon,
  "zhipu-intl-codingplan": zhipuIcon,
};

export function getProviderFallbackIcon(key: string) {
  if (key.includes("zhipu") || key.includes("bigmodel") || key.includes("z.ai")) {
    return zhipuIcon;
  }
  if (key.includes("kimi") || key.includes("moonshot")) {
    return kimiIcon;
  }
  if (key.includes("minimax")) {
    return minimaxIcon;
  }
  if (key.includes("azure") || key.includes("azure-openai")) {
    return azureOpenAiIcon;
  }
  if (key.includes("modelscope")) {
    return modelscopeIcon;
  }
  if (key.includes("openai")) {
    return openaiIcon;
  }
  if (key.includes("anthropic") || key.includes("claude")) {
    return anthropicIcon;
  }
  if (
    key.includes("dashscope")
    || key.includes("通义")
    || key.includes("qwen")
    || key.includes("阿里云百炼")
  ) {
    return dashscopeIcon;
  }
  if (key.includes("codingplan") || key.includes("aliyun") || key.includes("阿里")) {
    return aliyunCodingPlanIcon;
  }
  if (key.includes("deepseek")) {
    return deepseekIcon;
  }
  if (key.includes("glm") || key.includes("智谱")) {
    return zhipuIcon;
  }
  if (key.includes("gemini")) {
    return geminiIcon;
  }
  if (key.includes("copaw-local")) {
    return copawLocalIcon;
  }
  if (key.includes("lmstudio")) {
    return lmstudioIcon;
  }
  if (key.includes("ollama") || key.includes("local")) {
    return ollamaIcon;
  }

  return defaultIcon;
}
