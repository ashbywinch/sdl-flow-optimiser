# S1 confirmation — reply with the numbers of any WRONG labels (e.g. '12 34').
# Lines: [session] my label = classifier label, confidence, tool, intent.
# Delegation events (subtask coordination) inherit the parent phase.

## Sessions — repo · title · opening · first-20 tools
  S1  ompcfg  Create shell repo best practices skill
      open: We're going to make a new skill for making 
      tools: read×13 bash×6 todo×1
  S2  feed    Fix lint errors and verify report
      open: Read this proposal and turn it into a prd i
      tools: read×4 write×4 bash×3 edit×3
  S3  fam     Begin data acquisition planning phase
      open: Find the project plan and read it. Then sta
      tools: read×9 todo×5 ask×2 inspect_image×2
  S4  feed    Fix PR creation and deploy pipeline
      open: We made a plan to implement the component t
      tools: read×7 ask×6 grep×3 glob×2

## Disagreements (18) — adjudicate these
  1. [S1] prd≠exec read    0.35 "read chat-workflow"
  2. [S1] prd≠exec read    0.35 "read houses CI"
  3. [S1] prd≠exec read    0.35 "read test-first ru"
  4. [S1] prd≠exec read    0.35 "read side-by-side "
  5. [S1] prd≠exec read    0.35 "read DocConvention"
  6. [S3] flow≠exec read    0.35 "Listing all sessio"
  7. [S4] plan≠exec glob    0.35 "finding plan docs"
  8. [S1] exec≠prd grep    0.50 "locate pr-agent an"
  9. [S1] prd≠exec bash    0.60 "read pr-agent conf"
 10. [S2] tech≠prd read    0.60 "Read houses env ex"
 11. [S3] pr≠exec bash    0.60 "Confirming main st"
 12. [S4] pr≠exec bash    0.60 "committing and pus"
 13. [S4] pr≠exec bash    0.60 "applying protectio"
 14. [S2] prd≠tech read    0.75 "Read proposal PDF"
 15. [S3] flow≠tech todo    0.75 "Completing design "
 16. [S3] exec≠flow read    0.80 "Reading full trans"
 17. [S3] pr≠flow bash    0.80 "Committing and pus"
 18. [S3] exec≠pr edit    0.85 "Applying people.js"

## Agreed but low confidence (29) — spot check
 19. [S2] exec=exec hub     0.30 "Stop stuck spike"
 20. [S2] exec=exec hub     0.30 "Wait and check spi"
 21. [S2] exec=exec hub     0.30 "Follow spike log f"
 22. [S2] exec=exec hub     0.30 "Restart spike, k-m"
 23. [S2] exec=exec hub     0.30 "Describe spike exi"
 24. [S2] exec=exec hub     0.30 "Follow naming phas"
 25. [S2] exec=exec hub     0.30 "Run engine end-to-"
 26. [S3] exec=exec hub     0.30 "Starting no-cache "
 27. [S1] exec=exec read    0.35 "verify skill file "
 28. [S1] exec=exec read    0.35 "re-read skeleton a"
 29. [S1] exec=exec read    0.35 "re-read python and"
 30. [S1] exec=exec read    0.35 "final read of full"
 31. [S1] exec=exec read    0.35 "re-read repo creat"
 32. [S2] exec=exec read    0.35 "Read resumable imp"
 33. [S3] exec=exec glob    0.35 "Listing app views "
 34. [S3] exec=exec grep    0.35 "Finding how views "
 35. [S3] exec=exec read    0.35 "Reading cast view "
 36. [S3] exec=exec read    0.35 "Reading places tes"
 37. [S4] exec=exec read    0.35 "reading deploy tes"
 38. [S4] exec=exec grep    0.35 "checking picks pay"
 39. [S4] exec=exec read    0.35 "reading wrangler u"
 40. [S4] exec=exec grep    0.35 "checking RED run w"
 41. [S4] exec=exec read    0.35 "reading deployment"
 42. [S4] exec=exec read    0.35 "finding Response.r"
 43. [S4] exec=exec grep    0.35 "finding end of bui"
 44. [S4] exec=exec read    0.35 "reading full rende"
 45. [S4] exec=exec read    0.35 "finding end of tes"
 46. [S4] exec=exec read    0.35 "reading run_topic "
 47. [S4] exec=exec read    0.35 "reading evaluation"

## Delegation (4) — subtask coordination, context-inherited
 48. [S1] prd≠exec hub     0.50 "check scout jobs s"
 49. [S1] prd≠exec hub     0.50 "wait for remaining"
 50. [S1] exec=exec hub     0.50 "wait for one-shot "
 51. [S1] prd≠exec task    0.50 ""
