class AgentMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.7.1.tar.gz"
  sha256 "c9898d5ec63c0512286126b5688215ebfd83c0efc5315769257cdd03dd7ac5c5"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agent-memory 0.7.1", shell_output("#{bin}/agent-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agent-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agent-recall --help")
  end
end
