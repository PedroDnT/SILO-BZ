import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { DelosOracle } from "../target/types/delos_oracle";
import { assert } from "chai";
import { PublicKey, SystemProgram } from "@solana/web3.js";

describe("delos_oracle", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace.DelosOracle as Program<DelosOracle>;
  const authority = provider.wallet.publicKey;

  let macroPDA: PublicKey;
  let bump: number;

  before(async () => {
    [macroPDA, bump] = PublicKey.findProgramAddressSync(
      [Buffer.from("macro_state"), authority.toBuffer()],
      program.programId
    );
  });

  it("initialises the MacroState PDA", async () => {
    const tx = await program.methods
      .initialize()
      .accounts({
        authority,
        macroState: macroPDA,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    console.log("Initialize tx:", tx);

    const state = await program.account.macroState.fetch(macroPDA);
    assert.equal(state.authority.toBase58(), authority.toBase58());
    assert.equal(state.selicMeta.toNumber(), 0);
    assert.equal(state.bump, bump);
  });

  it("updates macro state with BCB data", async () => {
    // Representative BCB values as of early 2025:
    //   SELIC meta  = 13.25% → 1325 bp
    //   SELIC diária = 13.15% → 1315 bp
    //   CDI          = 13.15% → 1315 bp
    //   IPCA 12m     = 4.83%  → 483  bp
    //   IGP-M 12m    = 5.60%  → 560  bp
    //   USD/BRL      = 5.8921 → 58921
    const now = Math.floor(Date.now() / 1000);

    const tx = await program.methods
      .updateMacroState(
        new anchor.BN(1325),   // selic_meta
        new anchor.BN(1315),   // selic_diaria
        new anchor.BN(1315),   // cdi
        new anchor.BN(483),    // ipca
        new anchor.BN(560),    // igpm
        new anchor.BN(58921),  // usdbrl
        new anchor.BN(now),    // updated_ts
      )
      .accounts({
        authority,
        macroState: macroPDA,
      })
      .rpc();

    console.log("Update tx:", tx);

    const state = await program.account.macroState.fetch(macroPDA);
    assert.equal(state.selicMeta.toNumber(), 1325);
    assert.equal(state.ipca.toNumber(), 483);
    assert.equal(state.usdbrl.toNumber(), 58921);
    assert.isAbove(state.slot.toNumber(), 0);
    console.log("On-chain slot:", state.slot.toNumber());
  });

  it("rejects update from non-authority signer", async () => {
    const intruder = anchor.web3.Keypair.generate();

    // Airdrop to intruder so it can pay fees (localnet only)
    await provider.connection.requestAirdrop(
      intruder.publicKey,
      anchor.web3.LAMPORTS_PER_SOL
    );

    try {
      await program.methods
        .updateMacroState(
          new anchor.BN(9999),
          new anchor.BN(9999),
          new anchor.BN(9999),
          new anchor.BN(9999),
          new anchor.BN(9999),
          new anchor.BN(9999),
          new anchor.BN(0),
        )
        .accounts({
          authority: intruder.publicKey,
          macroState: macroPDA,
        })
        .signers([intruder])
        .rpc();
      assert.fail("Expected unauthorized error but call succeeded");
    } catch (err: any) {
      // Anchor wraps program errors; check for our error code
      assert.include(err.toString(), "Unauthorized");
    }
  });
});
