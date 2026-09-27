class AgentMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.9.7.tar.gz"
  sha256 "5cd1ba097cf3c87fa870b8a26f00ae37bf322aae1dff7367f4636f239b51ea91"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agent-memory 0.9.7", shell_output("#{bin}/agent-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agent-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agent-recall --help")
  end
end
