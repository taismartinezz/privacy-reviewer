import { supabase } from "../lib/supabase";

export async function handleSignOut() {
  await supabase.auth.signOut();
  window.location.href = "/login";
}
