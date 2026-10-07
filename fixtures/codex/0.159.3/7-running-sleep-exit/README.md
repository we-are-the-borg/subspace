# Running sleep interrupt with immediate exit

Session `01a0f736-96ac-7e83-9f87-260ac9ab8936`. A shell call started `sleep 30`, returned a running-process session ID, and was confirmed running before the wait turn was interrupted. The user then followed the immediate-exit scenario.

The capture contains pre + interrupt, with no post or stop before or after collection. This missing delivery does not prove that the child process was killed and cannot distinguish teardown from process completion without hook delivery.

Source files are the four raw capture JSON files for this session, from `1790853978-48985-AwN4hL.json` through `1790853984-49106-ZG4BVo.json`, numbered by captured delivery order.
