class AgiMemory < Formula
  include Language::Python::Virtualenv

  desc "Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants"
  homepage "https://github.com/kdbhalala/agi-memory"
  url "https://github.com/kdbhalala/agi-memory/archive/refs/tags/v0.9.3.tar.gz"
  sha256 "768d8155b11027c1d628834d7c3f5e3ff156a123e9d2f44d76f6d20883edecdd"
  license "MIT"
  head "https://github.com/kdbhalala/agi-memory.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "agi-memory 0.9.3", shell_output("#{bin}/agi-memory --version")
    assert_match "Turnkey integration tool", shell_output("#{bin}/agi-integrate --help")
    assert_match "Recall from agent session", shell_output("#{bin}/agi-recall --help")
  end
end
