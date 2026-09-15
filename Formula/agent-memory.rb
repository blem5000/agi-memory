class AgentMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.8.0.tar.gz"
  sha256 "18eecec3ddf43ddcadf2bf36f61a7a8298852d0f25e1535fef10da5bc5aa7634"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agent-memory 0.8.0", shell_output("#{bin}/agent-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agent-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agent-recall --help")
  end
end
